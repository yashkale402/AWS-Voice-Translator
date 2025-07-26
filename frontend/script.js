// Configuration - Replace with your actual API Gateway endpoint
const API_ENDPOINT = 'https://gcfrlyisng.execute-api.ap-south-1.amazonaws.com/prod/upload';
// Add your API key here if your API Gateway requires it
const API_KEY = ''; // Leave empty if not required

// DOM Elements
const recordButton = document.getElementById('recordButton');
const timer = document.getElementById('timer');
const statusMessage = document.getElementById('statusMessage');
const progressContainer = document.getElementById('progressContainer');
const progressBar = document.getElementById('progressBar');
const resultContainer = document.getElementById('resultContainer');
const originalText = document.getElementById('originalText');
const translatedText = document.getElementById('translatedText');
const translatedAudio = document.getElementById('translatedAudio');
const sourceLanguage = document.getElementById('sourceLanguage');
const targetLanguage = document.getElementById('targetLanguage');
const themeToggle = document.querySelector('.theme-toggle');

// Variables
let mediaRecorder;
let audioChunks = [];
let recordingStartTime;
let timerInterval;
let recordingDuration = 10000; // 10 seconds in milliseconds
let isDarkMode = false;
let statusCheckInterval;
let currentJobId;
let statusCheckCount = 0;
const MAX_STATUS_CHECKS = 10; // Limit status checks to prevent infinite loops

// Event Listeners
recordButton.addEventListener('click', toggleRecording);
themeToggle.addEventListener('click', toggleDarkMode);

// Check for saved theme preference
document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('darkMode') === 'true') {
        toggleDarkMode();
    }
    
    // Add animation to tech icons
    animateTechIcons();
});

// Functions
async function toggleRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        // Reset UI
        resetUI();
        
        // Clear any existing status check interval
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
            statusCheckInterval = null;
        }
        
        // Request microphone access
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Create MediaRecorder instance
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        
        // Event handlers
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };
        
        mediaRecorder.onstop = processAudio;
        
        // Start recording
        audioChunks = [];
        mediaRecorder.start();
        
        // Update UI
        recordButton.classList.add('recording');
        recordButton.querySelector('.btn-text').textContent = 'Stop Recording';
        statusMessage.textContent = 'Recording...';
        
        // Start timer
        recordingStartTime = Date.now();
        startTimer();
        
        // Auto-stop after recordingDuration
        setTimeout(() => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                stopRecording();
            }
        }, recordingDuration);
        
    } catch (error) {
        console.error('Error accessing microphone:', error);
        statusMessage.textContent = 'Error: Could not access microphone. Please check permissions.';
    }
}

function stopRecording() {
    if (mediaRecorder) {
        mediaRecorder.stop();
        clearInterval(timerInterval);
        
        // Stop all tracks in the stream
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        
        // Update UI
        recordButton.classList.remove('recording');
        recordButton.querySelector('.btn-text').textContent = 'Start Recording';
        statusMessage.textContent = 'Processing audio...';
    }
}

function startTimer() {
    clearInterval(timerInterval);
    
    timerInterval = setInterval(() => {
        const elapsedTime = Date.now() - recordingStartTime;
        const seconds = Math.floor((elapsedTime / 1000) % 60).toString().padStart(2, '0');
        const minutes = Math.floor((elapsedTime / 1000 / 60) % 60).toString().padStart(2, '0');
        
        timer.textContent = `${minutes}:${seconds}`;
        
        // Auto-stop if we reach the maximum duration
        if (elapsedTime >= recordingDuration) {
            stopRecording();
        }
    }, 100);
}

async function processAudio() {
    try {
        // Show progress
        progressContainer.classList.remove('hidden');
        animateProgress();
        
        // Create audio blob
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        
        // Create form data for upload
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        formData.append('sourceLanguage', sourceLanguage.value);
        formData.append('targetLanguage', targetLanguage.value);
        
        // Upload to API Gateway
        statusMessage.textContent = 'Uploading audio...';
        
        // IMPORTANT: DO NOT set Content-Type for FormData
        // Let the browser set it automatically with the correct boundary
        const headers = {};
        
        // Add API key if provided
        if (API_KEY) {
            headers['x-api-key'] = API_KEY;
        }
        
        console.log('Sending request to:', API_ENDPOINT);
        console.log('FormData contains audio:', formData.has('audio'));
        console.log('FormData contains sourceLanguage:', formData.has('sourceLanguage'));
        console.log('FormData contains targetLanguage:', formData.has('targetLanguage'));
        
        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: headers,
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`Server responded with ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        // Check if this is an asynchronous job
        if (result.jobId && result.status === 'PROCESSING') {
            currentJobId = result.jobId;
            statusMessage.textContent = 'Processing your audio...';
            
            // Reset status check count
            statusCheckCount = 0;
            
            // Start checking status
            startStatusCheck(result.jobId);
        } else {
            // Handle immediate result
            displayResults(result);
        }
        
    } catch (error) {
        console.error('Error processing audio:', error);
        statusMessage.textContent = `Error: ${error.message}`;
        progressContainer.classList.add('hidden');
    }
}

function startStatusCheck(jobId) {
    // Clear any existing interval
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    
    // Set up status check interval
    statusCheckInterval = setInterval(async () => {
        try {
            // Increment check count
            statusCheckCount++;
            
            // If we've checked too many times, stop checking
            if (statusCheckCount > MAX_STATUS_CHECKS) {
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;
                statusMessage.textContent = 'Processing timed out. Please try again.';
                progressContainer.classList.add('hidden');
                return;
            }
            
            const statusUrl = `${API_ENDPOINT}?jobId=${jobId}`;
            const response = await fetch(statusUrl);
            
            if (!response.ok) {
                throw new Error(`Server responded with ${response.status}: ${response.statusText}`);
            }
            
            const result = await response.json();
            
            if (result.status === 'COMPLETED') {
                // Job is complete, display results
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;
                displayResults(result);
            } else if (result.status === 'FAILED') {
                // Job failed
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;
                statusMessage.textContent = `Error: ${result.error || 'Processing failed'}`;
                progressContainer.classList.add('hidden');
            } else {
                // Still processing
                statusMessage.textContent = result.message || 'Still processing your audio...';
            }
            
        } catch (error) {
            console.error('Error checking job status:', error);
            
            // If we get an error, stop checking after a few attempts
            statusCheckCount++;
            if (statusCheckCount > 3) {
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;
                statusMessage.textContent = `Error checking status: ${error.message}`;
                progressContainer.classList.add('hidden');
            }
        }
    }, 3000); // Check every 3 seconds
}

function animateProgress() {
    let progress = 0;
    const interval = setInterval(() => {
        progress += 0.5;
        if (progress > 95) {
            clearInterval(interval);
        }
        progressBar.style.width = `${progress}%`;
    }, 500);
    
    // Store the interval ID to clear it when results are displayed
    window.progressInterval = interval;
}

function displayResults(result) {
    // Clear progress animation
    if (window.progressInterval) {
        clearInterval(window.progressInterval);
    }
    
    // Complete progress bar
    progressBar.style.width = '100%';
    
    // Update UI with results
    originalText.textContent = result.originalText || 'No text detected';
    translatedText.textContent = result.translatedText || 'Translation not available';
    
    if (result.audioUrl) {
        translatedAudio.src = result.audioUrl;
        translatedAudio.load();
    }
    
    // Show results container
    setTimeout(() => {
        progressContainer.classList.add('hidden');
        resultContainer.classList.remove('hidden');
        statusMessage.textContent = 'Translation complete!';
    }, 500);
}

function resetUI() {
    statusMessage.textContent = '';
    timer.textContent = '00:00';
    progressBar.style.width = '0%';
    progressContainer.classList.add('hidden');
    resultContainer.classList.add('hidden');
    currentJobId = null;
    statusCheckCount = 0;
}

function toggleDarkMode() {
    isDarkMode = !isDarkMode;
    document.body.classList.toggle('dark-mode');
    themeToggle.classList.toggle('active');
    
    // Change icon
    const icon = themeToggle.querySelector('i');
    if (isDarkMode) {
        icon.classList.remove('fa-moon');
        icon.classList.add('fa-sun');
    } else {
        icon.classList.remove('fa-sun');
        icon.classList.add('fa-moon');
    }
    
    // Save preference
    localStorage.setItem('darkMode', isDarkMode);
}

function animateTechIcons() {
    const techIcons = document.querySelectorAll('.tech-icon');
    techIcons.forEach((icon, index) => {
        setTimeout(() => {
            icon.style.opacity = '1';
            icon.style.transform = 'translateY(0)';
        }, 100 * index);
    });
}