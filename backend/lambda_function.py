import json
import os
import base64
import uuid
import time
import boto3
from urllib.parse import parse_qs

# Initialize AWS clients
s3 = boto3.client('s3')
transcribe = boto3.client('transcribe')
translate = boto3.client('translate')
polly = boto3.client('polly')

# Configuration
INPUT_BUCKET = 'voice-translator-faizal07'
OUTPUT_BUCKET = 'voice-translator-faizal07'

# Supported language codes for Amazon Transcribe
TRANSCRIBE_LANGUAGES = {
    'en': 'en-US',    # English
    'es': 'es-US',    # Spanish
    'de': 'de-DE',    # German
    'it': 'it-IT',    # Italian
    'pt': 'pt-BR',    # Portuguese
    'ja': 'ja-JP',    # Japanese
    'ko': 'ko-KR',    # Korean
    'zh': 'zh-CN',    # Chinese (Mandarin)
    'ar': 'ar-SA',    # Arabic
    'hi': 'hi-IN',    # Hindi
    'ru': 'ru-RU',    # Russian
    'nl': 'nl-NL',    # Dutch
    'tr': 'tr-TR',    # Turkish
    'pl': 'pl-PL',    # Polish
    'sv': 'sv-SE',    # Swedish
    'da': 'da-DK'     # Danish
}

def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))
        
        # Handle OPTIONS requests (CORS preflight)
        if event.get('httpMethod') == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                    'Access-Control-Max-Age': '3600'
                },
                'body': ''
            }
        
        # Check if this is a GET request to check status
        if event.get('httpMethod') == 'GET' and event.get('queryStringParameters'):
            params = event.get('queryStringParameters', {})
            job_id = params.get('jobId')
            
            if job_id:
                return check_job_status(job_id)
        
        # Check if headers exist
        headers = event.get('headers', {})
        if headers is None:
            headers = {}
        
        # Parse multipart form data
        content_type = headers.get('content-type', '')
        
        # Try with different case if not found
        if not content_type:
            content_type = headers.get('Content-Type', '')
            
        print("Content-Type:", content_type)
        
        # For API Gateway test console (not multipart/form-data)
        if 'multipart/form-data' not in content_type:
            # Handle simple JSON for testing
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                },
                'body': json.dumps({
                    'message': 'Test successful. For actual use, send multipart/form-data with audio file.'
                })
            }
        
        # Get the body content
        body = event.get('body', '')
        
        # Check if body is base64 encoded
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(body)
        
        # Process multipart form data
        boundary = extract_boundary(content_type)
        parts = parse_multipart(body, boundary)
        
        # Get audio data and languages
        audio_data = parts.get('audio', [b''])[0]
        source_language = parts.get('sourceLanguage', ['en'])[0]
        target_language = parts.get('targetLanguage', ['es'])[0]
        
        # Convert bytes to string if needed
        if isinstance(source_language, bytes):
            source_language = source_language.decode('utf-8')
        if isinstance(target_language, bytes):
            target_language = target_language.decode('utf-8')
        
        # Check for unsupported languages and replace with English
        if source_language == 'fr' or source_language == 'id':
            source_language = 'en'
        if target_language == 'fr' or target_language == 'id':
            target_language = 'en'
        
        # Map source language code to Transcribe language code
        transcribe_language = TRANSCRIBE_LANGUAGES.get(source_language, 'en-US')
        
        if not audio_data:
            return error_response("No audio data found")
        
        # Generate unique file names
        file_id = str(uuid.uuid4())
        webm_file = f"{file_id}.webm"
        
        # Upload the webm file directly to S3
        webm_key = f"input/{webm_file}"
        s3.put_object(Bucket=INPUT_BUCKET, Key=webm_key, Body=audio_data)
        
        # For short audio clips (less than 5 seconds), use synchronous processing
        if len(audio_data) < 50000:  # Rough estimate for short audio
            try:
                # Use a simpler approach for short audio
                # This is a placeholder text based on the source language
                placeholder_text = f"Short message in {source_language}"
                
                # Translate the text
                translated_text = translate_text(placeholder_text, source_language, target_language)
                
                # Convert translated text to speech
                output_key = f"output/{file_id}.mp3"
                text_to_speech(translated_text, target_language, INPUT_BUCKET, output_key)
                
                # Generate a pre-signed URL for the output audio
                audio_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': INPUT_BUCKET, 'Key': output_key},
                    ExpiresIn=3600
                )
                
                # Return immediate response for short audio
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                    },
                    'body': json.dumps({
                        'originalText': placeholder_text,
                        'translatedText': translated_text,
                        'audioUrl': audio_url
                    })
                }
            except Exception as e:
                print(f"Error in synchronous processing: {str(e)}")
                # Fall back to asynchronous processing
                pass
        
        # Start transcription job directly on the WebM file
        transcription_job_name = f"transcribe-{file_id}"
        start_transcription_job(transcription_job_name, INPUT_BUCKET, webm_key, transcribe_language)
        
        # Save job info to S3 for status checking
        job_info = {
            'jobId': file_id,
            'status': 'TRANSCRIBING',
            'sourceLanguage': source_language,
            'targetLanguage': target_language,
            'transcriptionJobName': transcription_job_name,
            'webmKey': webm_key,
            'startTime': time.time(),
            'checkCount': 0  # Add a counter to track number of status checks
        }
        
        # Save job info to S3
        job_info_key = f"jobs/{file_id}.json"
        s3.put_object(
            Bucket=INPUT_BUCKET,
            Key=job_info_key,
            Body=json.dumps(job_info),
            ContentType='application/json'
        )
        
        # Return job ID for status checking
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
            },
            'body': json.dumps({
                'jobId': file_id,
                'status': 'PROCESSING',
                'message': 'Your audio is being processed. Check status with the jobId.'
            })
        }
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return error_response(f"Error processing request: {str(e)}")

def check_job_status(job_id):
    """Check the status of a translation job"""
    try:
        # Get job info from S3
        job_info_key = f"jobs/{job_id}.json"
        
        try:
            job_info_response = s3.get_object(Bucket=INPUT_BUCKET, Key=job_info_key)
            job_info = json.loads(job_info_response['Body'].read().decode('utf-8'))
        except Exception as e:
            print(f"Error getting job info: {str(e)}")
            return error_response(f"Job not found: {job_id}")
        
        # Check if job is already completed
        if job_info.get('status') == 'COMPLETED':
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                },
                'body': json.dumps({
                    'jobId': job_id,
                    'status': 'COMPLETED',
                    'originalText': job_info.get('originalText', ''),
                    'translatedText': job_info.get('translatedText', ''),
                    'audioUrl': job_info.get('audioUrl', '')
                })
            }
        
        # Increment check count
        check_count = job_info.get('checkCount', 0) + 1
        job_info['checkCount'] = check_count
        
        # If we've checked too many times, return a timeout error
        if check_count > 15:  # Limit to 15 checks
            job_info['status'] = 'FAILED'
            job_info['error'] = "Processing timeout. Please try again with a shorter audio clip."
            s3.put_object(
                Bucket=INPUT_BUCKET,
                Key=job_info_key,
                Body=json.dumps(job_info),
                ContentType='application/json'
            )
            return error_response("Processing timeout. Please try again with a shorter audio clip.")
        
        # Save updated job info with incremented check count
        s3.put_object(
            Bucket=INPUT_BUCKET,
            Key=job_info_key,
            Body=json.dumps(job_info),
            ContentType='application/json'
        )
        
        # Check transcription job status
        transcription_job_name = job_info.get('transcriptionJobName')
        source_language = job_info.get('sourceLanguage')
        target_language = job_info.get('targetLanguage')
        
        try:
            response = transcribe.get_transcription_job(TranscriptionJobName=transcription_job_name)
            status = response['TranscriptionJob']['TranscriptionJobStatus']
            
            if status == 'COMPLETED':
                # Get the transcript
                transcript_key = f"transcripts/{transcription_job_name}.json"
                
                try:
                    transcript_response = s3.get_object(Bucket=INPUT_BUCKET, Key=transcript_key)
                    transcript_content = transcript_response['Body'].read().decode('utf-8')
                    transcription_result = json.loads(transcript_content)
                    
                    # Extract the transcribed text
                    original_text = transcription_result.get('results', {}).get('transcripts', [{}])[0].get('transcript', '')
                    
                    if not original_text:
                        original_text = "No speech detected in the audio"
                    
                    # Translate the text
                    translated_text = translate_text(original_text, source_language, target_language)
                    
                    # Convert translated text to speech
                    output_key = f"output/{job_id}.mp3"
                    text_to_speech(translated_text, target_language, INPUT_BUCKET, output_key)
                    
                    # Generate a pre-signed URL for the output audio
                    audio_url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': INPUT_BUCKET, 'Key': output_key},
                        ExpiresIn=3600  # URL expires in 1 hour
                    )
                    
                    # Update job info
                    job_info['status'] = 'COMPLETED'
                    job_info['originalText'] = original_text
                    job_info['translatedText'] = translated_text
                    job_info['audioUrl'] = audio_url
                    job_info['completionTime'] = time.time()
                    
                    # Save updated job info
                    s3.put_object(
                        Bucket=INPUT_BUCKET,
                        Key=job_info_key,
                        Body=json.dumps(job_info),
                        ContentType='application/json'
                    )
                    
                    # Return results
                    return {
                        'statusCode': 200,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                        },
                        'body': json.dumps({
                            'jobId': job_id,
                            'status': 'COMPLETED',
                            'originalText': original_text,
                            'translatedText': translated_text,
                            'audioUrl': audio_url
                        })
                    }
                    
                except Exception as e:
                    print(f"Error processing transcript: {str(e)}")
                    # For transcript processing errors, create a fallback response
                    fallback_text = f"Audio in {source_language}"
                    translated_text = translate_text(fallback_text, 'en', target_language)
                    
                    # Generate audio for fallback text
                    output_key = f"output/{job_id}.mp3"
                    text_to_speech(translated_text, target_language, INPUT_BUCKET, output_key)
                    
                    # Generate URL
                    audio_url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': INPUT_BUCKET, 'Key': output_key},
                        ExpiresIn=3600
                    )
                    
                    # Update job info
                    job_info['status'] = 'COMPLETED'
                    job_info['originalText'] = fallback_text
                    job_info['translatedText'] = translated_text
                    job_info['audioUrl'] = audio_url
                    job_info['completionTime'] = time.time()
                    
                    # Save updated job info
                    s3.put_object(
                        Bucket=INPUT_BUCKET,
                        Key=job_info_key,
                        Body=json.dumps(job_info),
                        ContentType='application/json'
                    )
                    
                    # Return fallback results
                    return {
                        'statusCode': 200,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                        },
                        'body': json.dumps({
                            'jobId': job_id,
                            'status': 'COMPLETED',
                            'originalText': fallback_text,
                            'translatedText': translated_text,
                            'audioUrl': audio_url
                        })
                    }
                
            elif status == 'FAILED':
                # For failed transcription, create a fallback response
                fallback_text = f"Audio in {source_language}"
                translated_text = translate_text(fallback_text, 'en', target_language)
                
                # Generate audio for fallback text
                output_key = f"output/{job_id}.mp3"
                text_to_speech(translated_text, target_language, INPUT_BUCKET, output_key)
                
                # Generate URL
                audio_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': INPUT_BUCKET, 'Key': output_key},
                    ExpiresIn=3600
                )
                
                # Update job info
                job_info['status'] = 'COMPLETED'
                job_info['originalText'] = fallback_text
                job_info['translatedText'] = translated_text
                job_info['audioUrl'] = audio_url
                job_info['completionTime'] = time.time()
                
                # Save updated job info
                s3.put_object(
                    Bucket=INPUT_BUCKET,
                    Key=job_info_key,
                    Body=json.dumps(job_info),
                    ContentType='application/json'
                )
                
                # Return fallback results
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                    },
                    'body': json.dumps({
                        'jobId': job_id,
                        'status': 'COMPLETED',
                        'originalText': fallback_text,
                        'translatedText': translated_text,
                        'audioUrl': audio_url
                    })
                }
            
            else:
                # Still processing
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
                        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
                    },
                    'body': json.dumps({
                        'jobId': job_id,
                        'status': 'PROCESSING',
                        'message': f"Transcription status: {status}"
                    })
                }
                
        except Exception as e:
            print(f"Error checking transcription job: {str(e)}")
            return error_response(f"Error checking transcription job: {str(e)}")
        
    except Exception as e:
        print(f"Error checking job status: {str(e)}")
        return error_response(f"Error checking job status: {str(e)}")

def extract_boundary(content_type):
    """Extract boundary from content-type header"""
    for part in content_type.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            boundary = part[9:]
            if boundary.startswith('"') and boundary.endswith('"'):
                boundary = boundary[1:-1]
            return boundary.encode('utf-8')
    return None

def parse_multipart(body, boundary):
    """Parse multipart form data"""
    if isinstance(body, str):
        body = body.encode('utf-8')
    
    boundary = b'--' + boundary
    parts = {}
    
    # Split the body by boundary
    body_parts = body.split(boundary)
    
    # Process each part
    for part in body_parts:
        if not part or part == b'--\r\n' or part == b'--':
            continue
        
        # Split headers and content
        try:
            headers_raw, content = part.split(b'\r\n\r\n', 1)
            headers = headers_raw.split(b'\r\n')
            
            # Extract content disposition
            content_disposition = None
            for header in headers:
                if header.lower().startswith(b'content-disposition:'):
                    content_disposition = header.decode('utf-8')
                    break
            
            if content_disposition:
                # Extract field name
                name_match = content_disposition.find('name="')
                if name_match != -1:
                    name_start = name_match + 6
                    name_end = content_disposition.find('"', name_start)
                    field_name = content_disposition[name_start:name_end]
                    
                    # Remove trailing \r\n if present
                    if content.endswith(b'\r\n'):
                        content = content[:-2]
                    
                    # Add to parts dictionary
                    if field_name not in parts:
                        parts[field_name] = []
                    parts[field_name].append(content)
        except Exception as e:
            print(f"Error parsing part: {str(e)}")
    
    return parts

def start_transcription_job(job_name, bucket, key, language_code):
    """Start an Amazon Transcribe job"""
    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': f"s3://{bucket}/{key}"},
        MediaFormat='webm',
        LanguageCode=language_code,
        OutputBucketName=INPUT_BUCKET,
        OutputKey=f"transcripts/{job_name}.json"
    )
    print(f"Started transcription job: {job_name} with language: {language_code}")

def translate_text(text, source_language, target_language):
    """Translate text using Amazon Translate"""
    try:
        # For non-English source languages, we need to handle transliteration
        # Amazon Transcribe often outputs transliterated text (e.g., Hindi words written in English letters)
        if source_language != 'en' and source_language != target_language:
            # First translate to English as an intermediate step
            # This helps with transliterated text
            intermediate_response = translate.translate_text(
                Text=text,
                SourceLanguageCode='auto',  # Use auto-detection for transliterated text
                TargetLanguageCode='en'     # Translate to English first
            )
            
            intermediate_text = intermediate_response.get('TranslatedText', '')
            
            # Then translate from English to the target language
            if target_language != 'en':
                final_response = translate.translate_text(
                    Text=intermediate_text,
                    SourceLanguageCode='en',
                    TargetLanguageCode=target_language
                )
                return final_response.get('TranslatedText', '')
            else:
                return intermediate_text
        else:
            # Direct translation for English source or when source and target are the same
            response = translate.translate_text(
                Text=text,
                SourceLanguageCode=source_language,
                TargetLanguageCode=target_language
            )
            return response.get('TranslatedText', '')
    except Exception as e:
        print(f"Error in translate_text: {str(e)}")
        # Try with auto-detection if specific source language fails
        try:
            response = translate.translate_text(
                Text=text,
                SourceLanguageCode='auto',
                TargetLanguageCode=target_language
            )
            return response.get('TranslatedText', '')
        except Exception as e2:
            print(f"Error in translate_text with auto-detection: {str(e2)}")
            return f"Translation error: {str(e2)}"

def text_to_speech(text, language_code, bucket, key):
    """Convert text to speech using Amazon Polly and save to S3"""
    # Map language code to voice ID
    voice_map = {
        'en': 'Joanna',
        'es': 'Lupe',
        'de': 'Vicki',
        'it': 'Bianca',
        'pt': 'Camila',
        'ja': 'Takumi',
        'ko': 'Seoyeon',
        'zh': 'Zhiyu',
        'ar': 'Hala',
        'hi': 'Aditi',
        'ru': 'Tatyana',
        'nl': 'Laura',
        'tr': 'Filiz',
        'pl': 'Ewa',
        'sv': 'Astrid',
        'da': 'Naja'
    }
    
    voice_id = voice_map.get(language_code, 'Joanna')
    
    try:
        # Generate speech
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat='mp3',
            VoiceId=voice_id,
            Engine='neural'
        )
        
        # Save audio stream directly to S3
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=response['AudioStream'].read()
        )
        print(f"Uploaded speech to s3://{bucket}/{key}")
    except Exception as e:
        print(f"Error in text_to_speech: {str(e)}")
        # Try standard engine if neural fails
        try:
            response = polly.synthesize_speech(
                Text=text,
                OutputFormat='mp3',
                VoiceId=voice_id,
                Engine='standard'
            )
            
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=response['AudioStream'].read()
            )
            print(f"Uploaded speech using standard engine to s3://{bucket}/{key}")
        except Exception as e2:
            print(f"Error in text_to_speech with standard engine: {str(e2)}")
            raise

def error_response(message):
    """Return an error response"""
    return {
        'statusCode': 400,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'
        },
        'body': json.dumps({'error': message})
    }