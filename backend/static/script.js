const API = "http://127.0.0.1:8000";

async function uploadFile() {
  const file = document.getElementById("pdfFile").files[0];
  if (!file) return alert("Select a PDF first.");

  const loader = document.getElementById("loader");
  loader.classList.remove("hidden");

  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API}/api/extract`, {
    method: "POST",
    body: formData
  });

  const data = await response.json();
  loader.classList.add("hidden");

  document.getElementById("result").innerHTML = `
    <div class="bg-slate-700 p-4 rounded-xl shadow-md">
      <p><strong>ID:</strong> ${data.extraction_id}</p>
      <p><strong>Pages:</strong> ${data.num_pages}</p>
      <p><strong>Machines:</strong> ${data.num_machines}</p>
      <button onclick="viewExtraction('${data.extraction_id}')"
        class="mt-3 bg-green-500 hover:bg-green-400 px-4 py-1 rounded transition shadow-md">
        View Details
      </button>
    </div>
  `;

  loadHistory();
  loadAnalytics();
}

async function loadHistory() {
  const response = await fetch(`${API}/api/extractions`);
  const data = await response.json();

  let html = "";
  data.extractions.forEach(ext => {
    html += `
      <div class="bg-slate-700 p-3 rounded-lg mb-2 hover:bg-slate-600 cursor-pointer transition"
        onclick="viewExtraction('${ext.extraction_id}')">
        <p>${ext.extraction_id}</p>
        <p class="text-sm text-gray-400">${ext.original_filename}</p>
      </div>
    `;
  });

  document.getElementById("history").innerHTML = html;
}

async function loadAnalytics() {
  const response = await fetch(`${API}/api/extractions`);
  const data = await response.json();

  document.getElementById("totalExtractions").innerText = data.total;

  let machineCount = 0;
  data.extractions.forEach(ext => {
    machineCount += ext.num_machines || 0;
  });

  document.getElementById("totalMachines").innerText = machineCount;
}

function viewExtraction(id) {
  window.location.href = `/static/extraction.html?id=${id}`;
}

loadHistory();
loadAnalytics();
