let currentRoomId = null;
let timerIntervals = {};
let allRoomsData = [];
let roomSortable = null;
let applianceSortable = null;
let webcamStream = null;
let monitoringStream = null;
let isMonitoring = false;
let model = null;
let monitoringIntervalId = null;
let monitoringVideo = null;

// DOM Elements
const monitoringCard = document.getElementById('ai-monitoring-card');
const monitoringStatus = document.getElementById('monitoring-status');
const webcamCanvas = document.createElement('canvas');
const webcamBtn = document.getElementById('open-webcam-btn');
const monitoringBtn = document.getElementById('start-monitoring-btn');
const liveWebcamVideo = document.getElementById('webcam-video-live');
const webcamCardContainer = document.getElementById('webcam-card-container');
const closeWebcamBtn = document.getElementById('close-webcam-btn');
const backToRoomsBtn = document.getElementById('back-to-rooms-btn');

// Confirmation Modal Elements
const confirmationModal = document.getElementById('confirmation-modal');
const confirmationTitle = document.getElementById('confirmation-title');
const confirmationMessage = document.getElementById('confirmation-message');
const confirmActionBtn = document.getElementById('confirm-action-btn');
const confirmCancelBtn = document.getElementById('confirm-cancel-btn');

// --- Utility Functions ---
const showNotification = (message, type) => {
    const notificationArea = document.getElementById('notification-area');
    const notification = document.createElement('div');
    notification.className = `p-4 rounded-lg shadow-md text-white transition-opacity duration-300 ease-in-out mb-2 transform translate-y-full opacity-0 ${type === 'on' ? 'bg-green-600' : 'bg-red-600'}`;
    notification.textContent = message;
    notificationArea.appendChild(notification);
    
    setTimeout(() => notification.classList.remove('translate-y-full', 'opacity-0'), 10);
    setTimeout(() => {
        notification.classList.add('opacity-0');
        setTimeout(() => notification.remove(), 500);
    }, 5000);
};

// API Helper Functions
const apiRequest = async (endpoint, data) => {
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        return { response, result };
    } catch (error) {
        console.error(`API request failed for ${endpoint}:`, error);
        throw error;
    }
};

const handleApiResponse = async (apiCall, successMessage, errorPrefix = 'Error') => {
    try {
        const { response, result } = await apiCall;
        if (response.ok) {
            showNotification(successMessage, 'on');
            return true;
        } else {
            showNotification(`${errorPrefix}: ${result.message}`, 'off');
            return false;
        }
    } catch (error) {
        showNotification(`Failed to perform operation.`, 'off');
        return false;
    }
};

// Modal Management
const modalActions = {
    'delete-room': {
        title: 'Delete Room',
        message: 'Are you sure you want to delete this room and all its appliances? This action cannot be undone.',
        handler: async (roomId) => {
            const success = await handleApiResponse(
                apiRequest('/api/delete-room', { room_id: roomId }),
                'Room deleted successfully!'
            );
            if (success) fetchRoomsAndAppliances();
        }
    },
    'delete-appliance': {
        title: 'Delete Appliance',
        message: 'Are you sure you want to delete this appliance? This action cannot be undone.',
        handler: async (roomId, applianceId) => {
            const success = await handleApiResponse(
                apiRequest('/api/delete-appliance', { room_id: roomId, appliance_id: applianceId }),
                'Appliance deleted successfully!'
            );
            if (success) {
                document.getElementById('settings-appliance-modal').classList.add('hidden');
                fetchRoomsAndAppliances();
            }
        }
    },
    'cancel-timer': {
        title: 'Cancel Timer',
        message: 'Are you sure you want to cancel the active timer?',
        handler: async (roomId, applianceId) => {
            const success = await handleApiResponse(
                apiRequest('/api/set-timer', { room_id: roomId, appliance_id: applianceId, timer: null }),
                'Timer cancelled.'
            );
            if (success) fetchRoomsAndAppliances();
        }
    }
};

const openConfirmationModal = (action, ...data) => {
    const actionConfig = modalActions[action];
    if (!actionConfig) return;
    
    confirmationTitle.textContent = actionConfig.title;
    confirmationMessage.textContent = actionConfig.message;
    confirmationModal.classList.remove('hidden');

    confirmActionBtn.onclick = async () => {
        confirmationModal.classList.add('hidden');
        await actionConfig.handler(...data);
    };
};

const sendApplianceState = async (roomId, applianceId, state) => {
    const success = await handleApiResponse(
        apiRequest('/api/set-appliance-state', { room_id: roomId, appliance_id: applianceId, state }),
        `Appliance turned ${state ? 'on' : 'off'}`
    );
    if (success) fetchRoomsAndAppliances();
};

const saveOrder = async (endpoint, data) => {
    try {
        await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    } catch (error) {
        console.error(`Failed to save order for ${endpoint}:`, error);
    }
};

const saveNewRoomOrder = (newOrder) => saveOrder('/api/save-room-order', { order: newOrder });
const saveNewApplianceOrder = (roomId, newOrder) => saveOrder('/api/save-appliance-order', { room_id: roomId, order: newOrder });

const fetchRoomsAndAppliances = async () => {
    try {
        const response = await fetch('/api/get-rooms-and-appliances');
        if (!response.ok) throw new Error('Failed to fetch rooms and appliances');
        
        const rooms = await response.json();
        allRoomsData = rooms;
        renderRooms(rooms);
        
        if (currentRoomId) {
            const room = rooms.find(r => r.id === currentRoomId);
            if (room) {
                renderAppliances(room.appliances, room.name);
            } else {
                showRoomsView();
            }
        }
    } catch (error) {
        console.error('Error fetching data:', error);
        showNotification('Failed to load data.', 'off');
    }
};

const showRoomsView = () => {
    currentRoomId = null;
    document.getElementById('rooms-view').classList.remove('hidden');
    document.getElementById('appliances-view').classList.add('hidden');
};

const showAppliancesView = () => {
    document.getElementById('rooms-view').classList.add('hidden');
    document.getElementById('appliances-view').classList.remove('hidden');
};

const createSortable = (container, onEndCallback) => {
    return new Sortable(container, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        onEnd: async (evt) => {
            if (evt.oldIndex !== evt.newIndex) {
                const newOrder = Array.from(container.children).map(child => child.dataset.id);
                await onEndCallback(newOrder);
            }
        }
    });
};

const renderRooms = (rooms) => {
    const container = document.getElementById('room-container');
    container.innerHTML = '';
    
    if (rooms.length > 0) {
        document.getElementById('rooms-view').classList.remove('hidden');
        document.getElementById('appliances-view').classList.add('hidden');
        
        rooms.forEach(room => {
            const roomCard = document.createElement('div');
            roomCard.setAttribute('data-slot', 'card');
            roomCard.setAttribute('data-id', room.id);
            roomCard.className = "bg-card text-card-foreground rounded-xl border p-6 shadow-sm transition-all relative";
            
            const aiControlStatus = room.ai_control ? 'Yes' : 'No';
            const aiStatusColor = room.ai_control ? 'text-green-500' : 'text-red-500';

            roomCard.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-xl font-bold cursor-pointer hover:underline" onclick="showAppliances('${room.id}')">${room.name}</h3>
                    <div class="flex space-x-2">
                        <button class="p-1 rounded-full hover:bg-muted transition-colors flex-shrink-0" title="Room Settings" onclick="event.stopPropagation(); openRoomSettings('${room.id}')">
                            <i class="h-4 w-4 fas fa-cog text-gray-400"></i>
                        </button>
                    </div>
                </div>
                <p class="text-gray-500">${room.appliances.length} Appliances</p>
                <p class="text-sm mt-2">AI Control: <span class="font-semibold ${aiStatusColor}">${aiControlStatus}</span></p>
            `;
            container.appendChild(roomCard);
        });
        
        if (roomSortable) roomSortable.destroy();
        roomSortable = createSortable(container, saveNewRoomOrder);
    } else {
        container.innerHTML = `<p class="text-center text-gray-500">No rooms added yet. Click "Add Room" to get started!</p>`;
    }
};

const updateTimerDisplay = (card, appliance) => {
    const timerElement = card.querySelector('.timer-display');
    const cancelButton = card.querySelector('.cancel-timer-btn');
    const toggleInput = card.querySelector('input[type="checkbox"]');
    if (!timerElement || !cancelButton || !toggleInput) return;

    clearInterval(timerIntervals[appliance.id]);

    if (appliance.timer && appliance.state) {
        const update = () => {
            const timeLeft = Math.floor(appliance.timer - Date.now() / 1000);
            if (timeLeft > 0) {
                const minutes = Math.floor(timeLeft / 60);
                const seconds = timeLeft % 60;
                timerElement.textContent = `Timer: ${minutes}m ${seconds}s`;
                timerElement.classList.remove('hidden');
                cancelButton.classList.remove('hidden');
            } else {
                timerElement.textContent = `Timer Off`;
                clearInterval(timerIntervals[appliance.id]);
                cancelButton.classList.add('hidden');
                sendApplianceState(currentRoomId, appliance.id, false);
                toggleInput.checked = false;
            }
        };
        update();
        timerIntervals[appliance.id] = setInterval(update, 1000);
    } else {
        timerElement.classList.add('hidden');
        cancelButton.classList.add('hidden');
    }
};

const renderAppliances = (appliances, roomName) => {
    const container = document.getElementById('appliance-container');
    container.innerHTML = '';
    const appliancesHeading = document.getElementById('appliances-heading');
    if (appliancesHeading) {
        appliancesHeading.textContent = `${roomName} Appliances`;
    }
    showAppliancesView();

    if (appliances.length > 0) {
        appliances.forEach(appliance => {
            const is_on = appliance.state;
            const is_locked = appliance.locked;
            const applianceCard = document.createElement('div');
            applianceCard.setAttribute('data-slot', 'card');
            applianceCard.setAttribute('data-id', appliance.id);
            applianceCard.className = "bg-card text-card-foreground rounded-xl border py-6 px-6 shadow-sm transition-all flex flex-col items-stretch relative";

            applianceCard.innerHTML = `
                <div class="flex items-center justify-between mb-4">
                    <div data-slot="card-title" class="leading-none font-semibold pr-2 flex items-center">
                        <span class="appliance-name">${appliance.name}</span>
                    </div>
                    <div class="flex items-center space-x-2">
                        <button class="p-1 rounded-full hover:bg-muted transition-colors flex-shrink-0" title="Set Manual Override" onclick="toggleLock('${currentRoomId}', '${appliance.id}')">
                            <i id="lock-icon-${appliance.id}" class="h-4 w-4 fas ${is_locked ? 'fa-lock text-red-500' : 'fa-unlock text-gray-400'}"></i>
                        </button>
                        <button class="p-1 rounded-full hover:bg-muted transition-colors flex-shrink-0" title="Set Timer" onclick="openTimerModal('${currentRoomId}', '${appliance.id}')">
                            <i class="h-4 w-4 fas fa-clock text-gray-400"></i>
                        </button>
                        <button class="p-1 rounded-full hover:bg-muted transition-colors flex-shrink-0" title="Appliance Settings" onclick="openApplianceSettings('${currentRoomId}', '${appliance.id}')">
                            <i class="h-4 w-4 fas fa-cog text-gray-400"></i>
                        </button>
                        <button class="p-1 rounded-full hover:bg-muted transition-colors flex-shrink-0 cancel-timer-btn hidden" title="Cancel Timer" onclick="openConfirmationModal('cancel-timer', '${currentRoomId}', '${appliance.id}')">
                            <i class="h-4 w-4 fas fa-times-circle text-red-400"></i>
                        </button>
                    </div>
                </div>
                <div data-slot="card-content" class="flex-grow flex items-center justify-between">
                    <i class="fas fa-lightbulb text-2xl ${is_on ? 'text-primary-accent' : 'text-gray-400 dark:text-gray-600'} transition-colors"></i>
                    <label class="custom-toggle-switch">
                        <input type="checkbox" data-room-id="${currentRoomId}" data-appliance-id="${appliance.id}" ${is_on ? 'checked' : ''}>
                        <span class="slider"></span>
                    </label>
                </div>
                <span class="timer-display absolute bottom-2 left-2 text-xs font-semibold text-primary-accent hidden"></span>
            `;
            container.appendChild(applianceCard);

            const toggleInput = applianceCard.querySelector('input[type="checkbox"]');
            toggleInput.onchange = () => {
                const newState = toggleInput.checked;
                sendApplianceState(currentRoomId, appliance.id, newState);
            };
            updateTimerDisplay(applianceCard, appliance);
        });
        
        if (applianceSortable) applianceSortable.destroy();
        applianceSortable = createSortable(container, (newOrder) => saveNewApplianceOrder(currentRoomId, newOrder));
    } else {
        container.innerHTML = `<p class="text-center text-gray-500">No appliances in this room yet. Click "Add Appliance" to get started!</p>`;
    }
};

const openRoomSettings = (roomId) => {
    const room = allRoomsData.find(r => r.id === roomId);
    if (!room) return;
    
    document.getElementById('edit-room-id').value = roomId;
    document.getElementById('edit-room-name').value = room.name;
    const aiControlSwitch = document.getElementById('ai-control-switch');
    aiControlSwitch.dataset.state = room.ai_control ? 'checked' : 'off';
    
    if (room.ai_control) {
        aiControlSwitch.classList.add('data-[state=checked]');
    } else {
        aiControlSwitch.classList.remove('data-[state=checked]');
    }
    document.getElementById('settings-room-modal').classList.remove('hidden');
};

const saveApplianceName = async (inputElement) => {
    const roomId = currentRoomId;
    const applianceId = inputElement.dataset.applianceId;
    const newName = inputElement.value;

    if (newName === "") {
        inputElement.value = "Unnamed Appliance";
        showNotification("Appliance name cannot be empty.", "off");
        return;
    }

    const success = await handleApiResponse(
        apiRequest('/api/set-appliance-name', { room_id: roomId, appliance_id: applianceId, name: newName }),
        `Appliance name updated to "${newName}".`
    );
    
    inputElement.disabled = true;
};

const openApplianceSettings = (roomId, applianceId) => {
    const room = allRoomsData.find(r => r.id === roomId);
    const appliance = room.appliances.find(a => a.id === applianceId);
    
    document.getElementById('edit-room-id').value = roomId;
    document.getElementById('edit-appliance-id').value = applianceId;
    document.getElementById('edit-appliance-name').value = appliance.name;
    document.getElementById('edit-appliance-relay').value = appliance.relay_number;
    
    const roomSelector = document.getElementById('edit-room-selector');
    roomSelector.innerHTML = '';
    allRoomsData.forEach(r => {
        const option = document.createElement('option');
        option.value = r.id;
        option.textContent = r.name;
        if (r.id === roomId) {
            option.selected = true;
        }
        roomSelector.appendChild(option);
    });
    
    const advancedSettingsToggle = document.querySelector('.advanced-settings-toggle');
    const advancedSettings = document.getElementById('advanced-settings');
    advancedSettingsToggle.onclick = () => {
        advancedSettings.classList.toggle('hidden');
    };

    document.getElementById('settings-appliance-modal').classList.remove('hidden');
};

const openTimerModal = async (roomId, applianceId) => {
    document.getElementById('timer-room-id').value = roomId;
    document.getElementById('timer-appliance-id').value = applianceId;
    document.getElementById('timer-modal').classList.remove('hidden');
};

const toggleLock = async (roomId, applianceId) => {
    try {
        const response = await fetch('/api/get-rooms-and-appliances');
        const rooms = await response.json();
        const appliance = rooms.find(r => r.id === roomId).appliances.find(a => a.id === applianceId);
        const newState = !appliance.locked;

        const success = await handleApiResponse(
            apiRequest('/api/set-lock', { room_id: roomId, appliance_id: applianceId, locked: newState }),
            `Appliance is now ${newState ? 'locked' : 'unlocked'}.`
        );
        if (success) fetchRoomsAndAppliances();
    } catch (error) {
        console.error(error);
        showNotification('Failed to update lock state.', 'off');
    }
};

// Webcam and Monitoring Functions
const toggleWebcam = async () => {
    const webcamVideo = document.getElementById('webcam-video-live');
    
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
            webcamVideo.srcObject = webcamStream;
            webcamCardContainer.classList.remove('hidden');
            webcamBtn.innerHTML = '<i class="fas fa-video-slash mr-2"></i>Close Webcam';
            showNotification('Webcam turned on.', 'on');
        } catch (err) {
            console.error("Error accessing webcam:", err);
            showNotification('Failed to access webcam. Please check permissions.', 'off');
        }
    }
};

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

const detectHumans = async (interval) => {
    if (!isMonitoring || !model) {
        console.log("Monitoring stopped or model not available.");
        return;
    }
    
    if (!monitoringVideo.srcObject) {
        console.log("Monitoring stream not available, stopping detection.");
        toggleMonitoring();
        return;
    }

    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = monitoringVideo.videoWidth;
    tempCanvas.height = monitoringVideo.videoHeight;
    const tempCtx = tempCanvas.getContext('2d');
    tempCtx.drawImage(monitoringVideo, 0, 0, tempCanvas.width, tempCanvas.height);
    
    const predictions = await model.detect(tempCanvas);
    const humanDetected = predictions.some(p => p.class === 'person');

    if (humanDetected) {
        const humanDetections = predictions.filter(p => p.class === 'person');
        console.log("Human detected. JSON response:", JSON.stringify(humanDetections, null, 2));
        monitoringStatus.textContent = 'Human detected! AI is in control.';
    } else {
        console.log("notfound");
        monitoringStatus.textContent = 'No human detected. Awaiting...';
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
        if (monitoringStream) {
            monitoringStream.getTracks().forEach(track => track.stop());
            monitoringStream = null;
        }
        if (currentRoomId) {
            await apiRequest('/api/update-room-settings', {
                room_id: currentRoomId,
                ai_control: false
            });
        }
    } else {
        try {
            if (!model) {
                showNotification('AI model is not loaded yet. Please wait a moment.', 'off');
                return;
            }

            const interval = prompt("Enter the time interval for AI monitoring (in seconds):");
            const parsedInterval = parseInt(interval);
            if (isNaN(parsedInterval) || parsedInterval <= 0) {
                showNotification('Invalid time interval. Monitoring not started.', 'off');
                return;
            }
            
            const stream = await navigator.mediaDevices.getUserMedia({ video: true });
            monitoringStream = stream;
            
            if (!monitoringVideo) {
                monitoringVideo = document.createElement('video');
                monitoringVideo.style.display = 'none';
                document.body.appendChild(monitoringVideo);
            }
            monitoringVideo.srcObject = monitoringStream;
            monitoringVideo.play();
            
            isMonitoring = true;
            monitoringCard.classList.remove('hidden');
            monitoringBtn.innerHTML = '<i class="fas fa-video-slash mr-2"></i>Stop Monitoring';
            showNotification('AI monitoring started.', 'on');
            
            if (currentRoomId) {
                await apiRequest('/api/update-room-settings', {
                    room_id: currentRoomId,
                    ai_control: true
                });
            }
           
            monitoringVideo.onloadedmetadata = () => {
                const monitoringInterval = parsedInterval * 1000;
                detectHumans(monitoringInterval);
            };

        } catch (err) {
            console.error("Error accessing webcam for monitoring:", err);
            showNotification('Failed to access webcam for monitoring. Please check permissions.', 'off');
            return;
        }
    }
};

const showAppliances = (roomId) => {
    const room = allRoomsData.find(r => r.id === roomId);
    if (room) {
        currentRoomId = roomId;
        renderAppliances(room.appliances, room.name);
    }
};

// Form Handlers
const handleTimerSubmit = async (e) => {
    e.preventDefault();
    const roomId = document.getElementById('timer-room-id').value;
    const applianceId = document.getElementById('timer-appliance-id').value;
    
    let timerTimestamp = null;
    const hours = parseInt(document.getElementById('timer-duration-hours').value) || 0;
    const minutes = parseInt(document.getElementById('timer-duration-minutes').value) || 0;
    const datetimeInput = document.getElementById('timer-datetime').value;

    if (hours > 0 || minutes > 0) {
        const timerDurationMinutes = hours * 60 + minutes;
        if (timerDurationMinutes > 0) {
            timerTimestamp = Math.floor(Date.now() / 1000) + timerDurationMinutes * 60;
        }
    } else if (datetimeInput) {
        const futureDate = new Date(datetimeInput);
        if (futureDate.getTime() > Date.now()) {
            timerTimestamp = Math.floor(futureDate.getTime() / 1000);
        }
    }

    if (timerTimestamp) {
        const success = await handleApiResponse(
            apiRequest('/api/set-timer', { room_id: roomId, appliance_id: applianceId, timer: timerTimestamp }),
            'Timer set successfully!'
        );
        if (success) {
            document.getElementById('timer-modal').classList.add('hidden');
            fetchRoomsAndAppliances();
        }
    } else {
        showNotification('Please set a valid future time or duration.', 'off');
    }
};

// Initialize all event listeners and modals
const initModalsAndListeners = () => {
    // Room management
    document.getElementById('add-room-btn').addEventListener('click', () => {
        document.getElementById('add-room-modal').classList.remove('hidden');
    });
    
    document.getElementById('cancel-room-btn').addEventListener('click', () => {
        document.getElementById('add-room-modal').classList.add('hidden');
    });
    
    document.getElementById('add-room-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const roomName = document.getElementById('new-room-name').value;
        const success = await handleApiResponse(
            apiRequest('/api/add-room', { name: roomName }),
            'Room added successfully!'
        );
        if (success) {
            document.getElementById('add-room-modal').classList.add('hidden');
            fetchRoomsAndAppliances();
        }
    });

    // Appliance management
    document.getElementById('add-appliance-btn').addEventListener('click', () => {
        document.getElementById('add-appliance-modal').classList.remove('hidden');
    });
    
    document.getElementById('cancel-appliance-btn').addEventListener('click', () => {
        document.getElementById('add-appliance-modal').classList.add('hidden');
    });
    
    document.getElementById('add-appliance-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const applianceName = document.getElementById('new-appliance-name').value;
        const relayNumber = document.getElementById('new-appliance-relay').value;
        const success = await handleApiResponse(
            apiRequest('/api/add-appliance', { room_id: currentRoomId, name: applianceName, relay_number: relayNumber }),
            'Appliance added successfully!'
        );
        if (success) {
            document.getElementById('add-appliance-modal').classList.add('hidden');
            fetchRoomsAndAppliances();
        }
    });

    // Settings forms
    document.getElementById('cancel-room-settings-btn').addEventListener('click', () => {
        document.getElementById('settings-room-modal').classList.add('hidden');
    });
    
    document.getElementById('delete-room-btn').addEventListener('click', () => {
        const roomId = document.getElementById('edit-room-id').value;
        openConfirmationModal('delete-room', roomId);
    });
    
    document.getElementById('settings-room-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const roomId = document.getElementById('edit-room-id').value;
        const newName = document.getElementById('edit-room-name').value;
        const aiControl = document.getElementById('ai-control-switch').dataset.state === 'checked';
        const success = await handleApiResponse(
            apiRequest('/api/update-room-settings', { room_id: roomId, name: newName, ai_control: aiControl }),
            'Room settings updated!'
        );
        if (success) {
            document.getElementById('settings-room-modal').classList.add('hidden');
            fetchRoomsAndAppliances();
        }
    });

    document.getElementById('cancel-appliance-settings-btn').addEventListener('click', () => {
        document.getElementById('settings-appliance-modal').classList.add('hidden');
    });
    
    document.getElementById('delete-appliance-btn').addEventListener('click', () => {
        const roomId = document.getElementById('edit-room-id').value;
        const applianceId = document.getElementById('edit-appliance-id').value;
        openConfirmationModal('delete-appliance', roomId, applianceId);
    });
    
    document.getElementById('settings-appliance-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const roomId = document.getElementById('edit-room-id').value;
        const applianceId = document.getElementById('edit-appliance-id').value;
        const newName = document.getElementById('edit-appliance-name').value;
        const newRelay = document.getElementById('edit-appliance-relay').value;
        const newRoomId = document.getElementById('edit-room-selector').value;
        
        const success = await handleApiResponse(
            apiRequest('/api/update-appliance-settings', { 
                room_id: roomId, 
                appliance_id: applianceId, 
                name: newName, 
                relay_number: newRelay, 
                new_room_id: newRoomId 
            }),
            'Appliance settings updated!'
        );
        if (success) {
            document.getElementById('settings-appliance-modal').classList.add('hidden');
            fetchRoomsAndAppliances();
        }
    });

    // Timer management
    document.getElementById('cancel-timer-btn').addEventListener('click', () => {
        document.getElementById('timer-modal').classList.add('hidden');
    });
    
    document.getElementById('timer-form').addEventListener('submit', handleTimerSubmit);

    // Navigation
    document.getElementById('back-to-rooms-btn').addEventListener('click', showRoomsView);

    // Confirmation modal
    confirmCancelBtn.addEventListener('click', () => {
        confirmationModal.classList.add('hidden');
    });

    // AI Control Switch
    document.getElementById('ai-control-switch').addEventListener('click', async (e) => {
        const switchBtn = e.currentTarget;
        const isChecked = switchBtn.dataset.state === 'checked';
        const roomId = document.getElementById('edit-room-id').value;

        const success = await handleApiResponse(
            apiRequest('/api/update-room-settings', { room_id: roomId, ai_control: !isChecked }),
            `AI Control is now ${!isChecked ? 'ON' : 'OFF'}.`
        );
        
        if (success) {
            if (isChecked) {
                switchBtn.dataset.state = 'off';
                switchBtn.classList.remove('data-[state=checked]');
            } else {
                switchBtn.dataset.state = 'checked';
                switchBtn.classList.add('data-[state=checked]');
            }
            fetchRoomsAndAppliances();
        }
    });

    // Webcam controls
    document.getElementById('open-webcam-btn').addEventListener('click', toggleWebcam);
    document.getElementById('close-webcam-btn').addEventListener('click', toggleWebcam);
    
    // Monitoring controls
    document.getElementById('start-monitoring-btn').addEventListener('click', toggleMonitoring);
    
    // Cleanup on page unload
    window.addEventListener('beforeunload', stopAllStreams);
};

// Initialize application
window.addEventListener('load', async () => {
    await fetchRoomsAndAppliances();
    setInterval(fetchRoomsAndAppliances, 3000);
    initModalsAndListeners();
    // loadModel(); // Uncomment when model loading function is available
});
