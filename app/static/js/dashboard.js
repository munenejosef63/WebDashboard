const APP_URLS = document.getElementById('app-urls').dataset;

// ----------------------------
// Application Initialization
// ----------------------------
document.addEventListener('DOMContentLoaded', () => {
    initializeApplication();
});

async function initializeApplication() {
    try {
        await Promise.all([
            populateStatusOptions(),
            setupFormValidations(),
            setupEventListeners()
        ]);
    } catch (error) {
        console.error('Application initialization failed:', error);
        showToast('Failed to initialize application', 'error');
    }
}

// ----------------------------
// Form Validations
// ----------------------------
function setupFormValidations() {
    // Section name validation
    const sectionNameInput = document.getElementById('newSectionName');
    if (sectionNameInput) {
        sectionNameInput.addEventListener('input', handleSectionNameValidation);
    }

    // Link URL validation
    const linkInput = document.getElementById('link');
    if (linkInput) {
        linkInput.addEventListener('input', handleLinkValidation);
    }
}

function handleSectionNameValidation(e) {
    const sectionName = e.target.value.trim();
    const errorDiv = document.getElementById('section-name-error');
    if (!errorDiv) return;

    errorDiv.textContent = sectionName.length > 255 ?
        'Section name cannot exceed 255 characters' : '';
    errorDiv.style.display = sectionName.length > 255 ? 'block' : 'none';
}

function handleLinkValidation(e) {
    const url = e.target.value.trim();
    const errorDiv = document.getElementById('link-error');
    if (!errorDiv) return;

    try {
        new URL(url);
        errorDiv.style.display = 'none';
    } catch {
        errorDiv.textContent = 'Please enter a valid URL';
        errorDiv.style.display = 'block';
    }
}

// ----------------------------
// Event Listeners
// ----------------------------
function setupEventListeners() {
    // File Upload Form
    const uploadForm = document.querySelector('form[enctype="multipart/form-data"]');
    if (uploadForm) {
        uploadForm.addEventListener('submit', handleFileUpload);
    }

    // Section Creation Form
    const sectionForm = document.getElementById('createSectionForm');
    if (sectionForm) {
        sectionForm.addEventListener('submit', handleSectionCreation);
    }

    // Link Creation Form
    const linkForm = document.getElementById('addLinkForm');
    if (linkForm) {
        linkForm.addEventListener('submit', handleLinkCreation);
    }
}

// ----------------------------
// File Upload Handling
// ----------------------------
async function handleFileUpload(e) {
    e.preventDefault();
    const form = e.target;
    const elements = initializeUploadElements();
    const formData = new FormData(form);

    resetUploadUI(elements);
    showUploadProgress(elements);

    try {
        const response = await fetch(APP_URLS.uploadUrl, {
            method: "POST",
            body: formData,
            credentials: 'same-origin'  // Important for sessions
        });

        // Check if the response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Invalid server response');
        }

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || 'Upload failed');
        }

        await handleUploadSuccess(elements, data, form);
        window.location.reload();  // Force refresh to update stats

    } catch (error) {
        handleUploadError(elements, error);
    }
}

function handleUploadSuccess(elements, data, form) {
    return new Promise((resolve) => {
        elements.progress.style.width = "100%";
        elements.percentage.textContent = "100%";
        elements.progress.classList.remove("progress-bar-animated", "progress-bar-striped");
        elements.successMessage.textContent = data.message;
        elements.successMessage.style.display = "block";

        Promise.allSettled([
            refreshSectionDropdown(),
            refreshStats()
        ]).then((results) => {
            const errors = results.filter(r => r.status === 'rejected');
            if (errors.length > 0) {
                console.error("Partial update failures:", errors);
                showToast('Upload successful with partial updates', 'warning');
            } else {
                showToast('File uploaded successfully!', 'success');
            }
            resolve();
        });

        // Cleanup after delay
        setTimeout(() => {
            elements.container.style.display = "none";
            elements.progress.style.width = "0%";
            elements.percentage.textContent = "";
            elements.status.textContent = "";
            elements.successMessage.style.display = "none";
            form.reset();
        }, 2000);
    });
}

// ----------------------------
// Progress Management
// ----------------------------
function showUploadProgress(elements) {
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress = Math.min(progress + Math.random() * 3, 90);
        elements.progress.style.width = `${progress}%`;
        elements.percentage.textContent = `${Math.floor(progress)}%`;
    }, 300);

    // Clear interval when request completes
    elements.progress.dataset.interval = progressInterval;
}

function resetUploadUI(elements) {
    clearInterval(elements.progress.dataset.interval);
    elements.progress.style.width = "0%";
    elements.percentage.textContent = "0%";
}

// ----------------------------
// Error Handling
// ----------------------------
function handleUploadError(elements, error) {
    console.error('Upload error:', error);

    // Add HTTP 413 specific handling
    if (error.message.includes('413')) {
        error.message = 'File too large. Max 10MB allowed.';
    }

    elements.status.textContent = `Error: ${error.message}`;
    elements.progress.classList.add("bg-danger");
    elements.successMessage.style.display = "none";

    showToast(error.message || 'Upload failed', 'error');

    setTimeout(() => {
        elements.container.style.display = "none";
        elements.progress.className = "progress-bar";
    }, 3000);
}

// ----------------------------
// Data Refresh Utilities
// ----------------------------
async function refreshSectionDropdown() {
    try {
        const response = await fetch(`${APP_URLS.getSectionsUrl}?_=${Date.now()}`);
        if (!response.ok) throw new Error('Failed to fetch sections');

        const sectionsHTML = await response.text();
        updateSectionUI(sectionsHTML);
        updateLinkFormDropdown(sectionsHTML);

    } catch (error) {
        console.error('Failed to refresh sections:', error);
        showToast('Failed to refresh sections list', 'error');
        throw error;
    }
}

function updateSectionUI(sectionsHTML) {
    const sectionList = document.querySelector('.horizontal-section-list');
    if (!sectionList) return;

    // Smooth transition for section list update
    sectionList.style.opacity = '0';
    setTimeout(() => {
        sectionList.innerHTML = sectionsHTML;
        sectionList.style.opacity = '1';
    }, 300);
}

function updateLinkFormDropdown(sectionsHTML) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(sectionsHTML, 'text/html');
    const sections = doc.querySelectorAll('.section-pill');
    const linkSectionSelect = document.getElementById('section');
    if (!linkSectionSelect) return;

    // Clear existing options while preserving first option
    const firstOption = linkSectionSelect.querySelector('option:first-child');
    linkSectionSelect.innerHTML = firstOption ? [firstOption.outerHTML] : [];

    sections.forEach(section => {
        const option = document.createElement('option');
        option.value = section.dataset.sectionId;
        option.textContent = section.textContent.trim();
        linkSectionSelect.appendChild(option);
    });
}

// ----------------------------
// Section Management
// ----------------------------
async function handleSectionCreation() {
    const spreadsheetSelect = document.getElementById('spreadsheetSelect');
    const sectionNameInput = document.getElementById('newSectionName');
    const submitButton = document.querySelector('#createSectionForm button[type="submit"]');

    try {
        // Validate inputs
        const spreadsheetId = spreadsheetSelect.value;
        const sectionName = sectionNameInput.value.trim();
        if (!spreadsheetId || !sectionName) {
            showToast('Please select a spreadsheet and enter a section name', 'warning');
            return;
        }
        if (sectionName.length > 255) {
            showToast('Section name cannot exceed 255 characters', 'error');
            return;
        }

        // Show loading state
        submitButton.disabled = true;
        submitButton.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"></div> Creating...';

        const response = await fetch(APP_URLS.createSectionUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                spreadsheet_id: spreadsheetId,
                section_name: sectionName
            })
        });

        const result = await response.json();
        if (!response.ok) throw result;

        // Success handling
        addNewSectionToUI(result.section);
        await refreshSectionDropdown();
        sectionNameInput.value = '';
        showToast('Section created successfully!', 'success');

    } catch (error) {
        handleSectionCreationError(error);
    } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Create Section';
    }
}

function handleSectionCreationError(error) {
    console.error('Section creation failed:', error);
    const errorMessage = error.message || 'Failed to create section';

    if (typeof errorMessage === 'string') {
        if (errorMessage.toLowerCase().includes('already exists')) {
            showToast('Section name already exists in this spreadsheet', 'error');
        } else if (errorMessage.includes('foreign key constraint')) {
            showToast('Invalid spreadsheet selection', 'error');
        } else {
            showToast(errorMessage, 'error');
        }
    } else {
        showToast('An unexpected error occurred', 'error');
    }
}

// ----------------------------
// Link Management
// ----------------------------
async function handleLinkCreation() {
    const formData = {
        section_id: document.getElementById('section').value,
        title: document.getElementById('title').value.trim(),
        url: document.getElementById('link').value.trim(),
        status: document.getElementById('status').value
    };

    try {
        if (!Object.values(formData).every(Boolean)) {
            throw new Error('All fields are required');
        }

        const response = await fetch(APP_URLS.addLinkUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw error;
        }

        const newLink = await response.json();
        addNewLinkToUI(newLink.link, formData.section_id);
        document.getElementById('addLinkForm').reset();
        showToast('Link added successfully!', 'success');

    } catch (error) {
        console.error('Link creation failed:', error);
        showToast(error.message || 'Failed to add link', 'error');
    }
}

// ----------------------------
// UI Utilities
// ----------------------------
function initializeUploadElements() {
    return {
        container: document.getElementById("upload-progress-container"),
        progress: document.getElementById("upload-progress"),
        status: document.getElementById("upload-status"),
        percentage: document.getElementById("upload-percentage"),
        successMessage: document.getElementById("upload-success-message"),
        statsFiles: document.querySelector('[data-stat="files"]'),
        statsSections: document.querySelector('[data-stat="sections"]'),
        statsLastUpload: document.querySelector('[data-stat="last-upload"]')
    };
}

function resetUploadUI(elements) {
    elements.progress.style.width = "";
    elements.percentage.textContent = "0%";
    elements.status.textContent = "";
    elements.container.style.display = "block";
    elements.successMessage.style.display = "none";
    elements.progress.className = "progress-bar progress-bar-striped progress-bar-animated";
}

// ----------------------------
// Status Management
// ----------------------------
async function populateStatusOptions() {
    const statusSelect = document.getElementById('status');
    if (!statusSelect) return;

    try {
        statusSelect.innerHTML = '<option value="" disabled>Loading statuses...</option>';
        const response = await fetch(APP_URLS.statusUrl);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const statuses = await response.json();
        statusSelect.innerHTML = '<option value="" disabled selected>Select Status</option>';

        if (statuses.length === 0) {
            statusSelect.innerHTML = '<option value="" disabled>No statuses found</option>';
            return;
        }

        statuses.forEach(status => {
            const option = document.createElement('option');
            option.value = status;
            option.textContent = status;
            statusSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load status options:', error);
        statusSelect.innerHTML = '<option value="" disabled>Error loading statuses</option>';
        showToast('Failed to load status options', 'error');
    }
}

// ----------------------------
// Notification System
// ----------------------------
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');

    toast.className = `toast toast-${type} show`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
        <div class="toast-body d-flex justify-content-between">
            <span>${message}</span>
            <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    toast.addEventListener('click', () => toast.remove());
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
}

// ----------------------------
// Helper Functions
// ----------------------------
function addNewSectionToUI(section) {
    const sectionsContainer = document.querySelector('.horizontal-section-list');
    if (!sectionsContainer) return;

    const newSection = document.createElement('div');
    newSection.className = 'section-pill';
    newSection.dataset.sectionId = section.id;
    newSection.innerHTML = `
        <a href="/section/${section.name}" class="section-link">
            ${section.name}
            <span class="badge bg-secondary ms-2">${section.spreadsheet_id}</span>
        </a>
    `;
    sectionsContainer.prepend(newSection);
}

function addNewLinkToUI(link, sectionId) {
    const linkList = document.querySelector(`#section-${sectionId} .link-list`);
    if (!linkList) return;

    const newLink = document.createElement('div');
    newLink.className = 'link-item visible';
    newLink.innerHTML = `
        <a href="${link.url}" class="${link.status}" target="_blank" rel="noopener noreferrer">
            ${link.title}
            <span class="badge bg-${getStatusColor(link.status)}">${link.status}</span>
        </a>
    `;
    linkList.prepend(newLink);
}

function getStatusColor(status) {
    const statusColors = {
        'active': 'success',
        'urgent': 'danger',
        'archived': 'secondary',
        'pending': 'warning',
        'completed': 'info'
    };
    return statusColors[status.toLowerCase()] || 'primary';
}


function setupUploadProgressPolling() {
    const progressElements = initializeUploadElements();
    let timeoutId = null;

    async function checkProgress() {
        try {
            const response = await fetch('/upload/progress');
            const data = await response.json();

            if (data.progress > 0) {
                progressElements.progress.style.width = `${data.progress}%`;
                progressElements.percentage.textContent = `${data.progress}%`;
                progressElements.status.textContent = data.status || '';
            }

            if (data.progress < 100) {
                timeoutId = setTimeout(checkProgress, 500);
            } else {
                progressElements.container.style.display = 'none';
            }
        } catch (error) {
            console.error('Progress check failed:', error);
            clearTimeout(timeoutId);
        }
    }

    // Start polling when upload starts
    document.getElementById('uploadForm').addEventListener('submit', () => {
        progressElements.container.style.display = 'block';
        timeoutId = setTimeout(checkProgress, 500);
    });
}

// Initialize when the page loads
document.addEventListener('DOMContentLoaded', setupUploadProgressPolling);