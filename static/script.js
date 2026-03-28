const API = "http://127.0.0.1:8000";

// --- UTILS: TOASTS & MODALS ---
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  
  const bgClass = type === 'success' ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-100' : 'bg-red-500/20 border-red-500/50 text-red-100';
  const icon = type === 'success' 
    ? `<svg class="w-5 h-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`
    : `<svg class="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`;

  toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-lg transform transition-all duration-300 translate-x-full opacity-0 ${bgClass}`;
  toast.innerHTML = `${icon} <span class="font-medium text-sm">${message}</span>`;

  container.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.classList.remove('translate-x-full', 'opacity-0');
  });

  // Remove after 3 seconds
  setTimeout(() => {
    toast.classList.add('translate-x-full', 'opacity-0');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// deleteTargetId stores { id, deletePdf } for the confirmation modal
let deleteTargetId = null;

/**
 * Called from the history card trash icon on the dashboard.
 * Opens the modal with both delete-mode options.
 */
function confirmDelete(id, event) {
  if (event) event.stopPropagation();
  deleteTargetId = id;
  const modal = document.getElementById('delete-modal');
  const modalContent = document.getElementById('delete-modal-content');
  if (modal && modalContent) {
    modal.classList.remove('hidden');
    setTimeout(() => {
      modal.classList.remove('opacity-0');
      modalContent.classList.remove('opacity-0', 'translate-y-4', 'scale-95');
    }, 10);
  }
}

function closeModal() {
  const modal = document.getElementById('delete-modal');
  const modalContent = document.getElementById('delete-modal-content');
  if (modal && modalContent) {
    modal.classList.add('opacity-0');
    modalContent.classList.add('opacity-0', 'translate-y-4', 'scale-95');
    setTimeout(() => {
      modal.classList.add('hidden');
      deleteTargetId = null;
    }, 300);
  }
}

// Bind modal buttons
document.addEventListener('DOMContentLoaded', () => {
  // "Delete Results Only" button
  const resultsOnlyBtn = document.getElementById('confirm-delete-results-btn');
  if (resultsOnlyBtn) {
    resultsOnlyBtn.addEventListener('click', async () => {
      if (deleteTargetId) {
        await executeDelete(deleteTargetId, false);
        closeModal();
      }
    });
  }

  // "Delete Results & PDF" button
  const fullDeleteBtn = document.getElementById('confirm-delete-full-btn');
  if (fullDeleteBtn) {
    fullDeleteBtn.addEventListener('click', async () => {
      if (deleteTargetId) {
        await executeDelete(deleteTargetId, true);
        closeModal();
      }
    });
  }
});

/**
 * Execute deletion.
 * deletePdf=false → only remove Excel outputs, keep card in history (list reloads)
 * deletePdf=true  → full delete, remove card from UI immediately
 */
async function executeDelete(id, deletePdf = false) {
  try {
    const res = await fetch(`${API}/api/extraction/${id}?delete_pdf=${deletePdf}`, { method: 'DELETE' });
    if (res.ok) {
      if (deletePdf) {
        // Full delete: remove the card from DOM, update counters
        showToast('Extraction fully deleted', 'success');
        const itemElement = document.getElementById(`ext-item-${id}`);
        if (itemElement) {
          itemElement.style.transition = 'opacity 0.3s, transform 0.3s';
          itemElement.style.opacity = '0';
          itemElement.style.transform = 'scale(0.95)';
          setTimeout(() => {
            itemElement.remove();
            loadAnalytics();
          }, 300);
        } else {
          loadHistory();
          loadAnalytics();
        }
      } else {
        // Results-only delete: entry still exists in DB, refresh the list
        showToast('Results deleted. Original PDF preserved.', 'success');
        loadHistory();
        loadAnalytics();
      }
    } else {
      const data = await res.json();
      showToast(data.detail || 'Failed to delete extraction', 'error');
    }
  } catch (err) {
    showToast('Network error during deletion', 'error');
  }
}

function addMachineSlot() {
  const container = document.getElementById('machine-inputs');
  const wrapper = document.createElement('div');
  wrapper.className = 'flex gap-2';
  wrapper.innerHTML = `
    <input type="text"
           placeholder="e.g. SM500"
           class="machine-name-input flex-1 bg-slate-800/60 border border-slate-600
                  rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm
                  focus:outline-none focus:border-cyan-500/60 transition"/>
    <button onclick="this.parentElement.remove()"
            class="px-3 rounded-xl bg-slate-700 hover:bg-red-500/20 text-slate-400
                   hover:text-red-400 border border-slate-600 transition text-sm">
      ✕
    </button>
  `;
  container.appendChild(wrapper);
}

function cancelMachineModal() {
  const modal = document.getElementById('machine-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  const input = document.getElementById('pdfFile');
  if (input) { input.value = ''; }
  if (typeof updateFileName === 'function') updateFileName(input);
}

async function uploadFile() {
  const input = document.getElementById('pdfFile');
  if (!input || !input.files || input.files.length === 0) {
    showToast('Please select a PDF file first.', 'error');
    return;
  }

  // Reset modal slots to one empty input
  const container = document.getElementById('machine-inputs');
  container.innerHTML = `
    <input type="text"
           placeholder="e.g. SPPR"
           class="machine-name-input w-full bg-slate-800/60 border border-slate-600
                  rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm
                  focus:outline-none focus:border-cyan-500/60 transition"/>
  `;

  // Show modal
  const modal = document.getElementById('machine-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

async function startExtraction() {
  const input = document.getElementById('pdfFile');
  if (!input || !input.files || input.files.length === 0) {
    showToast('No file selected.', 'error');
    cancelMachineModal();
    return;
  }

  // Collect non-empty machine names
  const rawInputs = document.querySelectorAll('.machine-name-input');
  const machineNames = Array.from(rawInputs)
    .map(el => el.value.trim().toUpperCase())
    .filter(name => name.length > 0);

  // Close modal
  const modal = document.getElementById('machine-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');

  // --- existing upload logic (identical to original uploadFile body) ---
  const file = input.files[0];
  const loader = document.getElementById("loader");
  const extractBtn = document.getElementById("extract-btn");
  const resultDiv = document.getElementById("result");
  const dropZoneDiv = document.getElementById("drop-zone");

  if (loader) loader.classList.remove("hidden", "flex-col", "flex");
  if (loader) loader.classList.add("flex");
  if (extractBtn) extractBtn.disabled = true;
  if (extractBtn) extractBtn.classList.add("opacity-50", "cursor-not-allowed");
  if (resultDiv) resultDiv.innerHTML = "";
  if (dropZoneDiv) dropZoneDiv.classList.add("opacity-50", "pointer-events-none");

  const formData = new FormData();
  formData.append("file", file);
  formData.append("machine_names", machineNames.join(','));

  try {
    const response = await fetch(`${API}/api/extract`, {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (response.ok) {
      showToast("Extraction successful!", "success");
      if (resultDiv) {
        resultDiv.innerHTML = `
          <div class="bg-emerald-900/20 border border-emerald-500/30 p-5 rounded-2xl shadow-lg animate-fade-in-up">
            <div class="flex items-center gap-3 mb-3">
              <div class="p-1.5 bg-emerald-500/20 rounded-full text-emerald-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 class="font-bold text-emerald-400">Processing Complete</h3>
            </div>
            <div class="grid grid-cols-2 gap-4 text-sm mb-4">
              <div class="bg-slate-800/50 p-3 rounded-xl border border-slate-700/50">
                <p class="text-slate-400 text-xs mb-1">ID</p>
                <p class="font-mono text-cyan-400 truncate" title="${data.extraction_id}">${data.extraction_id.split('_')[1] || data.extraction_id}</p>
              </div>
              <div class="bg-slate-800/50 p-3 rounded-xl border border-slate-700/50">
                <p class="text-slate-400 text-xs mb-1">Machines</p>
                <p class="font-semibold text-white">${data.num_machines}</p>
              </div>
            </div>
            <button onclick="viewExtraction('${data.extraction_id}')"
              class="w-full bg-slate-700 hover:bg-slate-600 text-white font-medium py-2 rounded-xl transition shadow-md flex items-center justify-center gap-2">
              <span>View Results</span>
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </button>
          </div>
        `;
      }
      input.value = "";
      if (typeof updateFileName === 'function') updateFileName(input);
      loadHistory();
      loadAnalytics();
    } else {
      showToast(data.detail || "Extraction failed.", "error");
    }
  } catch (error) {
    showToast("Network error during extraction.", "error");
  } finally {
    if (loader) loader.classList.add("hidden");
    if (loader) loader.classList.remove("flex");
    if (extractBtn) extractBtn.disabled = false;
    if (extractBtn) extractBtn.classList.remove("opacity-50", "cursor-not-allowed");
    if (dropZoneDiv) dropZoneDiv.classList.remove("opacity-50", "pointer-events-none");
  }
}

// Add CSS animation for result card if not present in main css
const style = document.createElement('style');
style.textContent = `
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .animate-fade-in-up {
    animation: fadeInUp 0.4s ease-out forwards;
  }
`;
document.head.appendChild(style);


async function loadHistory() {
  const historyContainer = document.getElementById("history");
  if (!historyContainer) return;

  // Show skeletons
  historyContainer.innerHTML = Array(3).fill(0).map(() => `
    <div class="p-4 rounded-xl bg-slate-800/40 border border-slate-700/50 animate-pulse flex justify-between items-center">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-slate-700/50 rounded-lg"></div>
        <div>
          <div class="h-4 w-32 bg-slate-700/50 rounded mb-2"></div>
          <div class="h-3 w-20 bg-slate-700/30 rounded"></div>
        </div>
      </div>
      <div class="h-4 w-16 bg-slate-700/50 rounded"></div>
    </div>
  `).join('');

  try {
    const response = await fetch(`${API}/api/extractions`);
    const data = await response.json();

    if (data.extractions.length === 0) {
      historyContainer.innerHTML = `
        <div class="text-center py-10 text-slate-500">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto mb-3 opacity-20" fill="none" viewBox="0 0 24 24" stroke="currentColor">
             <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
          <p>No extractions found.</p>
        </div>
      `;
      return;
    }

    let html = "";
    data.extractions.forEach(ext => {
      // Determine status icon and color
      const isFailed = ext.status === 'failed';
      const statusColor = isFailed ? 'text-red-400' : 'text-emerald-400';
      const bgColor = isFailed ? 'bg-red-400/10' : 'bg-emerald-400/10';
      const icon = isFailed 
        ? `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`
        : `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;

      html += `
        <div id="ext-item-${ext.extraction_id}" class="group p-4 rounded-xl bg-slate-800/30 border border-slate-700/50 hover:bg-slate-700/30 hover:border-cyan-500/30 transition-all duration-300 flex justify-between items-center cursor-pointer shadow-sm hover:shadow-cyan-900/10" onclick="viewExtraction('${ext.extraction_id}')">
          
          <div class="flex items-center gap-4">
            <div class="p-2 rounded-lg ${bgColor} ${statusColor}">
              ${icon}
            </div>
            <div>
              <p class="font-semibold text-slate-200 truncate max-w-[200px] md:max-w-xs" title="${ext.original_filename}">${ext.original_filename}</p>
              <div class="flex items-center gap-2 mt-1">
                <span class="text-xs font-mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">${ext.extraction_id.split('_')[1] || ext.extraction_id}</span>
                <span class="text-[10px] text-slate-400">${new Date(ext.uploaded_at).toLocaleDateString()}</span>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-4">
            <div class="text-right hidden sm:block">
              <span class="text-cyan-400 font-medium">${ext.num_machines || 0}</span>
              <span class="text-xs text-slate-500 block">machines</span>
            </div>
            
            <!-- DELETE BUTTON -->
            <button onclick="confirmDelete('${ext.extraction_id}', event)" class="p-2 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100" title="Delete Extraction">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>

        </div>
      `;
    });

    historyContainer.innerHTML = html;
  } catch (err) {
    historyContainer.innerHTML = `<div class="p-4 text-red-400 text-sm text-center">Failed to load history</div>`;
  }
}

async function loadAnalytics() {
  try {
    const response = await fetch(`${API}/api/extractions`);
    const data = await response.json();
    
    // Animate numbers if element exists
    const totalExtEl = document.getElementById("totalExtractions");
    const totalMachEl = document.getElementById("totalMachines");
    
    if (totalExtEl) totalExtEl.innerText = data.total;

    let machineCount = 0;
    data.extractions.forEach(ext => {
      machineCount += ext.num_machines || 0;
    });

    if (totalMachEl) totalMachEl.innerText = machineCount;
  } catch (err) {
    console.error("Failed to load analytics");
  }
}

function viewExtraction(id) {
  window.location.href = `/static/extraction.html?id=${id}`;
}

loadHistory();
loadAnalytics();
