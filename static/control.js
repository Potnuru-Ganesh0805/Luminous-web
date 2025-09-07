import { showNotification } from './themes.js';

let currentRoomId = null;
let timerIntervals = {};
let allRoomsData = [];
let roomSortable = null;
let applianceSortable = null;
let webcamStream = null;
let isMonitoring = false;
let model = null;
let monitoringIntervalId = null;
let monitoringVideo = null; // Separate video element for monitoring
const monitoringCard = document.getElementById('ai-monitoring-card');
const monitoringStatus = document.getElementById('monitoring-status');
const webcamCanvas = document.createElement('canvas'); // Hidden canvas for processing
const webcamBtn = document.getElementById('open-webcam-btn');
const monitoringBtn = document.getElementById('start-monitoring-btn');
const liveWebcamVideo = document.getElementById('webcam-video-live');
const webcamCardContainer = document.getElementById('webcam-card-container');

// Load the COCO-SSD model
const loadModel = async () => {
    try {
        monitoringStatus.textContent = 'Loading AI model...';
        model = await cocoSsd.load();
        monitoringStatus.textContent = 'AI model loaded successfully.';
        console.log('AI model loaded successfully.');
    } catch (error) {
        console.error('Failed to load model:', error);
        monitoringStatus.textContent = 'Failed to load AI model.';
        showNotification('Failed to load AI model.', 'off');
    }
};

const detectHumans = async (interval) => {
    if (!isMonitoring || !model) {
        console.log("Monitoring stopped or model not available.");
        return;
    }
    
    // Check if the monitoring stream is still active
    if (!monitoringVideo.srcObject) {
        console.log("Monitoring stream not available, stopping detection.");
        toggleMonitoring();
        return;
    }

    // Draw the video frame to the canvas for detection
    const ctx = webcamCanvas.getContext('2d');
    ctx.drawImage(monitoringVideo, 0, 0, webcamCanvas.width, webcamCanvas.height);
    
    const predictions = await model.detect(webcamCanvas);
    const humanDetected = predictions.some(p => p.class === 'person');

    if (humanDetected) {
        const humanDetections = predictions.filter(p => p.class === 'person');
        console.log("Human detected. JSON response:", JSON.stringify(humanDetections, null, 2));
        monitoringStatus.textContent = `Human detected! AI is in control of Room ${allRoomsData.find(r => r.id === currentRoomId)?.name}.`;
    } else {
        console.log("notfound");
        monitoringStatus.textContent = `No human detected. Awaiting...`;
    }
    
    if (isMonitoring) {
         monitoringIntervalId = setTimeout(() => detectHumans(interval), interval);
    }
};

const toggleMonitoring = async () => {
    if (isMonitoring) {
        isMonitoring = false;
        monitoringCard.classList.add('hidden');
        monitoringBtn.innerHTML = '<i class="fas fa-eye mr-2"></i>Start Monitoring';
        showNotification('AI monitoring stopped.', 'on');
        if (monitoringIntervalId) {
             clearTimeout(monitoringIntervalId);
             monitoringIntervalId = null;
        }
        if (monitoringVideo && monitoringVideo.srcObject) {
             monitoringVideo.srcObject.getTracks().forEach(track => track.stop());
        }
        if(currentRoomId) {
            await fetch('/api/update-room-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_id: currentRoomId, ai_control: false })
            });
        }
    } else {
        // Start Monitoring
        try {
             if (!model) {
                 showNotification('AI model is not loaded yet. Please wait or refresh the page.', 'off');
                 return;
             }

             const interval = prompt("Enter the time interval for AI monitoring (in seconds):");
             const parsedInterval = parseInt(interval);
             if (isNaN(parsedInterval) || parsedInterval <= 0) {
                 showNotification('Invalid time interval. Monitoring not started.', 'off');
                 return;
             }
             
             const stream = await navigator.mediaDevices.getUserMedia({ video: true });
             
             if (!monitoringVideo) {
                monitoringVideo = document.createElement('video');
                monitoringVideo.style.display = 'none';
                document.body.appendChild(monitoringVideo);
             }
             monitoringVideo.srcObject = stream;
             monitoringVideo.play();
             
             isMonitoring = true;
             monitoringCard.classList.remove('hidden');
             monitoringBtn.innerHTML = '<i class="fas fa-video-slash mr-2"></i>Stop Monitoring';
             showNotification('AI monitoring started.', 'on');
             
             if(currentRoomId) {
                await fetch('/api/update-room-settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room_id: currentRoomId, ai_control: true })
                });
             }
            
            monitoringVideo.onloadedmetadata = () => {
                detectHumans(parsedInterval * 1000);
            };

        } catch (err) {
             console.error("Error accessing webcam for monitoring:", err);
             showNotification('Failed to access webcam for monitoring. Please check permissions.', 'off');
             return;
        }
    }
};

// Toggle webcam functionality for live feed
const toggleWebcam = async () => {
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
        webcamCardContainer.classList.add('hidden');
        webcamBtn.innerHTML = '<i class="fas fa-camera mr-2"></i>Open Webcam';
        showNotification('Webcam turned off.', 'on');
    } else {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true });
            webcamStream = stream;
            liveWebcamVideo.srcObject = stream;
            webcamCardContainer.classList.remove('hidden');
            webcamBtn.innerHTML = '<i class="fas fa-video-slash mr-2"></i>Close Webcam';
            showNotification('Webcam turned on.', 'on');
        } catch (err) {
            console.error("Error accessing webcam:", err);
            showNotification('Failed to access webcam. Please check permissions.', 'off');
        }
    }
};

// Utility function to stop all streams
const stopAllStreams = () => {
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }
    if (isMonitoring) {
        isMonitoring = false;
        if (monitoringStream) {
            monitoringStream.getTracks().forEach(track => track.stop());
            monitoringStream = null;
        }
        if (monitoringIntervalId) {
            clearTimeout(monitoringIntervalId);
            monitoringIntervalId = null;
        }
    }
};

// Event listeners
document.getElementById('open-webcam-btn').addEventListener('click', toggleWebcam);
document.getElementById('close-webcam-btn').addEventListener('click', toggleWebcam);
document.getElementById('start-monitoring-btn').addEventListener('click', toggleMonitoring);
window.addEventListener('beforeunload', stopAllStreams);

// Initialization on window load
window.onload = async () => {
    await fetchRoomsAndAppliances();
    setInterval(fetchRoomsAndAppliances, 3000); // Polling for real-time updates
    loadModel(); // Load the AI model on page load
    initModals(); // Initialize modal event listeners
    initListeners(); // Initialize other event listeners
};
