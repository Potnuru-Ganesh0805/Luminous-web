// Universal Confirmation Modal Logic
export const openConfirmationModal = (action, ...data) => {
    const confirmationModal = document.getElementById('confirmation-modal');
    const confirmationTitle = document.getElementById('confirmation-title');
    const confirmationMessage = document.getElementById('confirmation-message');
    const confirmActionBtn = document.getElementById('confirm-action-btn');
    const confirmCancelBtn = document.getElementById('confirm-cancel-btn');

    let currentAction = action;
    let currentData = data;
    if (action === 'delete-room') {
        confirmationTitle.textContent = 'Delete Room';
        confirmationMessage.textContent = 'Are you sure you want to delete this room and all its appliances? This action cannot be undone.';
    } else if (action === 'delete-appliance') {
        confirmationTitle.textContent = 'Delete Appliance';
        confirmationMessage.textContent = 'Are you sure you want to delete this appliance? This action cannot be undone.';
    } else if (action === 'cancel-timer') {
        confirmationTitle.textContent = 'Cancel Timer';
        confirmationMessage.textContent = 'Are you sure you want to cancel the active timer?';
    }
    confirmationModal.classList.remove('hidden');

    confirmActionBtn.onclick = async () => {
        confirmationModal.classList.add('hidden');
        // Your logic to handle the actions goes here
        if (currentAction === 'delete-room') {
            const [roomId] = currentData;
            try {
                const response = await fetch('/api/delete-room', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room_id: roomId })
                });
                const result = await response.json();
                if (response.ok) {
                    showNotification('Room deleted successfully!', 'on');
                    fetchRoomsAndAppliances();
                } else {
                    showNotification(`Error: ${result.message}`, 'off');
                }
            } catch (error) {
                console.error(error);
                showNotification('Failed to delete room.', 'off');
            }
        } else if (currentAction === 'delete-appliance') {
            const [roomId, applianceId] = currentData;
            try {
                const response = await fetch('/api/delete-appliance', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room_id: roomId, appliance_id: applianceId })
                });
                const result = await response.json();
                if (response.ok) {
                    showNotification('Appliance deleted successfully!', 'on');
                    document.getElementById('settings-appliance-modal').classList.add('hidden');
                    fetchRoomsAndAppliances();
                } else {
                    showNotification(`Error: ${result.message}`, 'off');
                }
            } catch (error) {
                console.error(error);
                showNotification('Failed to delete appliance.', 'off');
            }
        } else if (currentAction === 'cancel-timer') {
            const [roomId, applianceId] = currentData;
            try {
                const response = await fetch('/api/set-timer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room_id: roomId, appliance_id: applianceId, timer: null })
                });
                const result = await response.json();
                if (response.ok) {
                    showNotification('Timer cancelled.', 'on');
                    fetchRoomsAndAppliances();
                } else {
                    showNotification(`Error: ${result.message}`, 'off');
                }
            } catch (error) {
                console.error(error);
                showNotification('Failed to cancel timer.', 'off');
            }
        }
        currentAction = null;
        currentData = null;
    };
    
    confirmCancelBtn.onclick = () => {
        confirmationModal.classList.add('hidden');
        currentAction = null;
        currentData = null;
    };

};
