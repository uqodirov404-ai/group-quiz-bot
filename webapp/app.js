const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const initData = tg.initData;
let currentUser = null;

// Tab Switching
window.switchTab = function(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const targetTab = document.getElementById('tab-' + tabId);
    if(targetTab) targetTab.classList.add('active');
    
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.classList.remove('text-emerald-500');
    });
    const activeBtn = document.querySelector(.nav-btn[data-target=" + tabId + "]);
    if(activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.color = '#10b981';
    }
    document.querySelectorAll('.nav-btn:not(.active)').forEach(btn => {
        btn.style.color = '#9ca3af';
    });
    
    if (tabId === 'experts') loadExperts();
    if (tabId === 'cabinet') loadCabinet();
    if (tabId === 'admin') loadAdminPanel();
}

// Image Preview
window.previewImages = function(input, previewId) {
    const container = document.getElementById(previewId);
    container.innerHTML = '';
    if (input.files) {
        Array.from(input.files).forEach(file => {
            const reader = new FileReader();
            reader.onload = function(e) {
                const img = document.createElement('img');
                img.src = e.target.result;
                img.className = 'image-preview';
                container.appendChild(img);
            }
            reader.readAsDataURL(file);
        });
    }
}

// Initial Load
async function initApp() {
    try {
        const res = await fetch('/api/user', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ initData })
        });
        if (res.ok) {
            currentUser = await res.json();
            if (currentUser.is_admin) {
                document.getElementById('navAdmin').classList.remove('hidden');
            }
            // Populate Home tab user info
            const userNameEl = document.getElementById('userName');
            const userInitialEl = document.getElementById('userInitial');
            if (userNameEl && currentUser.first_name) {
                userNameEl.innerText = currentUser.first_name;
                userInitialEl.innerText = currentUser.first_name.charAt(0).toUpperCase();
            }
        }
    } catch(e) { console.error(e); }
}

// Tab 1: AI Check Submit
document.getElementById('aiForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnText = document.getElementById('aiBtnText');
    const loader = document.getElementById('aiLoader');
    btnText.innerText = 'Yuborilmoqda...';
    loader.classList.remove('hidden');
    
    const formData = new FormData();
    formData.append('initData', initData);
    formData.append('criteria', document.getElementById('aiCriteria').value);
    formData.append('topic', document.getElementById('aiTopic').value);
    formData.append('text', document.getElementById('aiText').value);
    
    const files = document.getElementById('aiFiles').files;
    for(let i=0; i<files.length; i++) {
        formData.append('files', files[i]);
    }
    
    try {
        await fetch('/api/upload_ai', { method: 'POST', body: formData });
        tg.showAlert("Essengiz AI ga yuborildi. Natijani bot orqali kuting!");
        document.getElementById('aiForm').reset();
        document.getElementById('aiPreview').innerHTML = '';
    } catch(err) {
        tg.showAlert("Xatolik yuz berdi.");
    } finally {
        btnText.innerText = 'Tekshirishga yuborish';
        loader.classList.add('hidden');
    }
});

// Tab 2: Experts List
async function loadExperts() {
    document.getElementById('orderForm').classList.add('hidden');
    const container = document.getElementById('expertList');
    container.innerHTML = '<div class="text-center py-10"><div class="loader mx-auto"></div></div>';
    try {
        const res = await fetch('/api/experts');
        const experts = await res.json();
        container.innerHTML = '';
        if (experts.length === 0) {
            container.innerHTML = '<p class="text-center text-gray-500 font-medium">Faol ekspertlar yoq.</p>';
            return;
        }
        experts.forEach(exp => {
            const stars = exp.reviews > 0 ? '⭐'.repeat(Math.round(exp.rating)) : 'Yangi 🌟';
            container.innerHTML += 
                <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 flex flex-col">
                    <div class="flex items-center gap-3 mb-2">
                        <div class="w-12 h-12 bg-orange-100 text-orange-600 rounded-full flex items-center justify-center text-xl font-bold">
                             + exp.name.charAt(0) + 
                        </div>
                        <div>
                            <h3 class="font-bold text-lg text-gray-900"> + exp.name + </h3>
                            <p class="text-xs text-orange-500 font-bold"> + stars +  ( + exp.reviews +  sharh)</p>
                        </div>
                    </div>
                    <p class="text-sm text-gray-600 italic mb-4 bg-gray-50 p-3 rounded-xl border border-gray-100">" + exp.bio + "</p>
                    <button onclick="openOrderForm( + exp.id + )" class="w-full bg-orange-50 hover:bg-orange-100 text-orange-600 font-bold py-3 rounded-2xl transition">Tanlash</button>
                </div>
            ;
        });
    } catch(e) { container.innerHTML = '<p class="text-center text-red-500">Xatolik yuz berdi</p>'; }
}

window.openOrderForm = async function(expId) {
    document.getElementById('orderExpertId').value = expId;
    document.getElementById('expertList').innerHTML = '';
    document.getElementById('orderForm').classList.remove('hidden');
    
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();
        document.getElementById('orderPrice').innerText = settings.price;
        document.getElementById('orderCard').innerText = settings.card;
    } catch(e){}
}

window.closeOrderForm = function() {
    document.getElementById('orderForm').classList.add('hidden');
    loadExperts();
}

// Tab 2: Order Submit
document.getElementById('humanForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnText = document.getElementById('humanBtnText');
    const loader = document.getElementById('humanLoader');
    btnText.innerText = 'Yuborilmoqda...';
    loader.classList.remove('hidden');
    
    const formData = new FormData();
    formData.append('initData', initData);
    formData.append('expert_id', document.getElementById('orderExpertId').value);
    formData.append('text', document.getElementById('orderText').value);
    formData.append('receipt', document.getElementById('orderReceipt').files[0]);
    
    const files = document.getElementById('orderFiles').files;
    for(let i=0; i<files.length; i++) {
        formData.append('files', files[i]);
    }
    
    try {
        await fetch('/api/upload_human', { method: 'POST', body: formData });
        tg.showAlert("Chek va esse yuborildi. Admin tasdiqlashi bilan ekspertga yuboriladi!");
        closeOrderForm();
    } catch(err) {
        tg.showAlert("Xatolik yuz berdi.");
    } finally {
        btnText.innerText = 'Yuborish';
        loader.classList.add('hidden');
    }
});

// Tab 3: Cabinet
window.loadCabinet = async function() {
    const container = document.getElementById('cabinetContent');
    container.innerHTML = '<div class="text-center py-10"><div class="loader mx-auto"></div></div>';
    
    if (!currentUser) await initApp();
    
    let html = 
        <!-- Balans Card -->
        <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 flex items-center justify-between mb-4">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 rounded-2xl bg-green-100 text-green-500 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-wallet"></i>
                </div>
                <div>
                    <p class="text-xs text-gray-500 font-medium">Balans</p>
                    <p class="text-xl font-bold text-gray-900"> + currentUser.balance +  so'm</p>
                </div>
            </div>
            <button onclick="tg.showAlert('Tez kunda!')" class="bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2 px-4 rounded-xl shadow-md shadow-emerald-200 transition">To'ldirish</button>
        </div>

        <!-- AI Kreditlar Card -->
        <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 flex items-center justify-between mb-4 relative overflow-hidden">
            <div class="flex items-center gap-4 relative z-10">
                <div class="w-12 h-12 rounded-2xl bg-indigo-100 text-indigo-500 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-wand-magic-sparkles"></i>
                </div>
                <div>
                    <p class="text-xs text-gray-500 font-medium">AI kreditlar</p>
                    <p class="text-2xl font-bold text-gray-900 leading-tight">2 <span class="text-lg">ta</span></p>
                    <p class="text-xs text-gray-400 mt-1">1 kredit = 5 000 so'm</p>
                </div>
            </div>
            <button onclick="tg.showAlert('Tez kunda!')" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 px-5 rounded-xl shadow-md shadow-blue-200 transition relative z-10">Sotib Olish</button>
            <div class="absolute -bottom-10 -right-10 w-32 h-32 bg-blue-50 rounded-full blur-2xl z-0"></div>
        </div>

        <!-- Menu List Card -->
        <div class="bg-white rounded-3xl shadow-card border border-gray-100 mb-4 overflow-hidden">
            <button onclick="tg.showAlert('Esselaringiz shu yerda chiqadi')" class="w-full flex items-center justify-between p-5 border-b border-gray-50 hover:bg-gray-50 transition text-left">
                <div class="flex items-center gap-4">
                    <div class="w-10 h-10 rounded-xl bg-green-100 text-green-500 flex items-center justify-center">
                        <i class="fa-regular fa-file-lines text-lg"></i>
                    </div>
                    <div>
                        <p class="font-bold text-gray-900 text-[15px]">Essalarim</p>
                        <p class="text-[11px] text-gray-500 mt-0.5">Yuborilgan va tekshirilgan esselar</p>
                    </div>
                </div>
                <i class="fa-solid fa-chevron-right text-gray-300 text-sm"></i>
            </button>
            <button onclick="tg.showAlert('Tranzaksiyalar tarixi')" class="w-full flex items-center justify-between p-5 hover:bg-gray-50 transition text-left">
                <div class="flex items-center gap-4">
                    <div class="w-10 h-10 rounded-xl bg-lime-100 text-lime-500 flex items-center justify-center">
                        <i class="fa-regular fa-clock text-lg"></i>
                    </div>
                    <div>
                        <p class="font-bold text-gray-900 text-[15px]">Tranzaksiyalar tarixi</p>
                        <p class="text-[11px] text-gray-500 mt-0.5">To'lovlar va kredit harakatlari</p>
                    </div>
                </div>
                <i class="fa-solid fa-chevron-right text-gray-300 text-sm"></i>
            </button>
        </div>

        <!-- Referal tizim Card -->
        <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 mb-6">
            <div class="flex items-center gap-4 mb-4">
                <div class="w-12 h-12 rounded-2xl bg-sky-100 text-sky-500 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-gift"></i>
                </div>
                <div>
                    <h3 class="font-bold text-gray-900 text-lg">Referal tizim</h3>
                    <p class="text-xs text-gray-500 mt-0.5">Har 2 ta do'st taklif qiling — 1 AI kredit oling</p>
                </div>
            </div>
            <div class="flex items-center justify-center py-2 relative">
                <div class="w-1/2 text-center">
                    <p class="text-2xl font-bold text-emerald-500">0</p>
                    <p class="text-xs text-gray-500 mt-1">Taklif qilingan</p>
                </div>
                <div class="h-10 w-px bg-gray-100 absolute left-1/2"></div>
                <div class="w-1/2 text-center">
                    <p class="text-2xl font-bold text-emerald-500">0</p>
                    <p class="text-xs text-gray-500 mt-1">Olingan kredit</p>
                </div>
            </div>
        </div>
    ;
    
    if (currentUser.expert) {
        const exp = currentUser.expert;
        if (exp.status === 'active') {
            html += 
                <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 mt-5">
                    <h3 class="font-bold text-lg mb-4 flex items-center gap-2 text-gray-900"><i class="fa-solid fa-briefcase text-indigo-500"></i> Ekspert Profili</h3>
                    <div class="flex gap-4 mb-5">
                        <div class="bg-green-50 text-green-700 p-3 rounded-2xl flex-1 text-center border border-green-100">
                            <p class="text-xs font-bold uppercase">Daromad</p>
                            <p class="font-bold"> + exp.earned +  <span class="text-xs">UZS</span></p>
                        </div>
                        <div class="bg-yellow-50 text-yellow-700 p-3 rounded-2xl flex-1 text-center border border-yellow-100">
                            <p class="text-xs font-bold uppercase">Reyting</p>
                            <p class="font-bold"> + exp.rating + ⭐</p>
                        </div>
                    </div>
                    <button onclick="loadExpertTasks()" class="w-full bg-gray-900 text-white rounded-2xl py-3.5 font-bold shadow-lg hover:bg-black transition">Yangi esselarni ko'rish</button>
                    <div id="expertTasksArea" class="mt-4 space-y-3"></div>
                </div>
            ;
        } else if (exp.status === 'pending') {
            html += <div class="bg-yellow-50 text-yellow-700 p-4 rounded-2xl mt-5 text-center text-sm font-bold border border-yellow-200"><i class="fa-solid fa-clock mr-1"></i> Arizangiz ko'rib chiqilmoqda...</div>;
        } else {
            html += <div class="bg-red-50 text-red-600 p-4 rounded-2xl mt-5 text-center text-sm font-bold border border-red-200"><i class="fa-solid fa-circle-xmark mr-1"></i> Arizangiz rad etilgan.</div>;
        }
    } else {
        html += 
            <div class="bg-white rounded-3xl p-5 shadow-card border border-gray-100 mt-5">
                <h3 class="font-bold text-lg mb-2 text-gray-900"><i class="fa-solid fa-award text-indigo-500 mr-1"></i> Ekspert bo'lish</h3>
                <p class="text-sm text-gray-500 mb-4 font-medium">Esselarni tekshirib pul ishlashni xohlasangiz, ekspertlikka ariza topshiring.</p>
                <textarea id="applyBio" rows="3" placeholder="O'zingiz va tajribangiz haqida yozing..." class="w-full rounded-2xl border-gray-200 bg-gray-50 p-3.5 mb-3 text-sm outline-none focus:ring-2 focus:ring-indigo-500"></textarea>
                <button onclick="applyExpert()" class="w-full bg-indigo-50 text-indigo-600 font-bold py-3 rounded-2xl transition hover:bg-indigo-100">Ariza topshirish</button>
            </div>
        ;
    }
    
    container.innerHTML = html;
}

window.applyExpert = async function() {
    const bio = document.getElementById('applyBio').value;
    if(!bio) return;
    await fetch('/api/apply_expert', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ initData, bio }) });
    tg.showAlert("Arizangiz adminga yuborildi!");
    currentUser.expert = { status: 'pending' };
    loadCabinet();
}

window.loadExpertTasks = async function() {
    const container = document.getElementById('expertTasksArea');
    container.innerHTML = '<div class="loader mx-auto"></div>';
    try {
        const res = await fetch('/api/expert/tasks?initData=' + encodeURIComponent(initData));
        const tasks = await res.json();
        container.innerHTML = '';
        if(tasks.length === 0) {
            container.innerHTML = '<p class="text-sm text-center text-gray-500 font-medium">Hozircha yangi esse yoq.</p>';
            return;
        }
        tasks.forEach(t => {
            let photosHtml = '';
            if (t.photo_id) photosHtml = '<p class="text-sm text-indigo-500 font-medium mb-2"><i class="fa-solid fa-image"></i> Rasm botga yuborilgan.</p>';
            container.innerHTML += 
                <div class="border-2 border-gray-100 rounded-2xl p-4 bg-gray-50">
                    <p class="text-xs font-bold text-gray-400 mb-2 uppercase">Esse # + t.id + </p>
                     + photosHtml + 
                    <p class="text-sm mb-3 font-medium text-gray-800"> + (t.text || '') + </p>
                    <textarea id="reply_ + t.id + " rows="3" placeholder="Xulosa yozing..." class="w-full rounded-xl border border-gray-200 p-3 text-sm mb-3 outline-none focus:ring-2 focus:ring-indigo-500"></textarea>
                    <button onclick="sendReply( + t.id + )" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2.5 rounded-xl text-sm w-full font-bold transition shadow-md shadow-indigo-200">Javob yuborish</button>
                </div>
            ;
        });
    } catch(e) {}
}

window.sendReply = async function(id) {
    const text = document.getElementById('reply_' + id).value;
    if(!text) return;
    try {
        await fetch('/api/expert/reply', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ initData, essay_id: id, reply_text: text }) });
        tg.showAlert("Javobingiz mijozga yuborildi!");
        loadExpertTasks();
    } catch(e) {}
}

// Tab 4: Admin
async function loadAdminPanel() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();
        document.getElementById('adminPrice').value = settings.price;
        document.getElementById('adminCard').value = settings.card;
        
        const expertsRes = await fetch('/api/experts');
        const experts = await expertsRes.json();
        
        const list = document.getElementById('adminExpertsList');
        list.innerHTML = '';
        if(experts.length === 0) list.innerHTML = '<p class="text-sm text-gray-500 font-medium">Faol ekspertlar yoq.</p>';
        experts.forEach(exp => {
            list.innerHTML += 
                <div class="flex items-center justify-between bg-white p-4 rounded-2xl border border-gray-100 shadow-sm">
                    <div>
                        <p class="font-bold text-sm text-gray-900"> + exp.name + </p>
                        <p class="text-xs text-gray-500 font-medium mt-1">ID:  + exp.id + </p>
                    </div>
                    <button onclick="removeExpert( + exp.id + )" class="text-red-600 bg-red-50 hover:bg-red-100 px-3 py-2 rounded-xl text-xs font-bold transition"><i class="fa-solid fa-trash-can mr-1"></i> O'chirish</button>
                </div>
            ;
        });
    } catch(e) {}
}

window.saveAdminSettings = async function() {
    const price = document.getElementById('adminPrice').value;
    const card = document.getElementById('adminCard').value;
    await fetch('/api/admin/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ initData, price, card }) });
    tg.showAlert("Sozlamalar saqlandi!");
}

window.removeExpert = async function(id) {
    if(confirm("Haqiqatan ham o'chirmoqchimisiz?")) {
        await fetch('/api/admin/remove_expert', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ initData, expert_id: id }) });
        tg.showAlert("O'chirildi!");
        loadAdminPanel();
    }
}

// Startup
switchTab('home');
initApp();
