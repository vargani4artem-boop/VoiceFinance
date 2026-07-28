/**
 * VoiceFinance Main App Orchestrator
 */

document.addEventListener('DOMContentLoaded', () => {
    // Component instances
    const nlu = new NLUParser();
    const charts = new FinanceCharts();
    let voiceEngine = null;

    // State
    let transactions = [];
    let analyticsData = { income: 0, expense: 0, balance: 0, ratio: 0 };
    
    // Filter State
    let filterMonth = 'all';
    let filterCategory = 'all';
    let filterSearch = '';
    let filterDateCutoff = null;

    // DOM Elements
    const voiceBtn = document.getElementById('voiceBtn');
    const voiceBtnIcon = document.getElementById('voiceBtnIcon');
    const voiceStatus = document.getElementById('voiceStatus');
    const voiceSubtext = document.getElementById('voiceSubtext');
    const voiceCanvas = document.getElementById('voiceWaveform');

    const metricIncome = document.getElementById('metricIncome');
    const metricExpense = document.getElementById('metricExpense');
    const metricBalance = document.getElementById('metricBalance');
    const metricRatio = document.getElementById('metricRatio');
    const metricRatioText = document.getElementById('metricRatioText');
    const txList = document.getElementById('txList');
    const txCount = document.getElementById('txCount');

    const compareCard = document.getElementById('compareCard');
    const btnCloseCompare = document.getElementById('btnCloseCompare');

    const addModal = document.getElementById('addModal');
    const btnManualAdd = document.getElementById('btnManualAdd');
    const btnCloseModal = document.getElementById('btnCloseModal');
    const addTxForm = document.getElementById('addTxForm');

    const btnExportCSV = document.getElementById('btnExportCSV');
    const btnExportPDF = document.getElementById('btnExportPDF');
    
    // Filter DOM Elements
    const filterMonthEl = document.getElementById('filterMonth');
    const filterCategoryEl = document.getElementById('filterCategory');
    const filterSearchEl = document.getElementById('filterSearch');

    // Initialize Voice Engine
    voiceEngine = new VoiceEngine({
        canvas: voiceCanvas,
        onStatusChange: (text, listening) => {
            voiceStatus.innerText = text;
            if (listening) {
                voiceBtn.classList.add('listening');
                voiceBtnIcon.className = 'fa-solid fa-waveform';
            } else {
                voiceBtn.classList.remove('listening');
                voiceBtnIcon.className = 'fa-solid fa-microphone';
            }
        },
        onCommand: (commandText) => {
            handleVoiceCommand(commandText);
        }
    });

    voiceBtn.addEventListener('click', () => {
        voiceEngine.toggleListening();
    });

    // Preset Hint Tags click handlers
    document.querySelectorAll('.hint-tag').forEach(tag => {
        tag.addEventListener('click', () => {
            const cmd = tag.getAttribute('data-cmd');
            if (cmd) {
                voiceStatus.innerText = `"${cmd}"`;
                handleVoiceCommand(cmd);
            }
        });
    });

    /**
     * Handle Voice Command Input
     */
    async function handleVoiceCommand(rawText) {
        const parsed = nlu.parse(rawText);
        console.log('[App] Parsed Voice Command:', parsed);

        switch (parsed.intent) {
            case 'ADD_TRANSACTION':
                const newTx = await addTransaction({
                    type: parsed.type,
                    amount: parsed.amount,
                    currency: parsed.currency,
                    category: parsed.category,
                    description: parsed.description,
                    raw_voice: parsed.raw
                });

                const typeText = parsed.type === 'income' ? 'Доход' : 'Расход';
                const msg = `${typeText} ${parsed.amount} долларов на ${parsed.category} сохранён!`;
                showToast(msg, 'success');
                voiceEngine.speak(msg);
                break;

            case 'QUERY_RATIO':
                const ratioVal = analyticsData.ratio || 0;
                const ratioMsg = ratioVal > 1 
                    ? `Ваши доходы больше расходов в ${ratioVal} раз.`
                    : `Ваши расходы превышают доходы! Коэффициент: ${ratioVal}.`;
                showToast(ratioMsg, 'info');
                voiceEngine.speak(ratioMsg);
                break;

            case 'QUERY_TOP_EXPENSE':
                const catTotals = calculateCategoryTotals();
                const sorted = Object.entries(catTotals).sort((a, b) => b[1] - a[1]);
                if (sorted.length > 0) {
                    const topMsg = `Ваш главный расход по категориям: ${sorted[0][0]} — ${sorted[0][1]} долларов.`;
                    showToast(topMsg, 'info');
                    voiceEngine.speak(topMsg);
                } else {
                    voiceEngine.speak('У вас пока нет записанных расходов.');
                }
                break;

            case 'COMPARE_CATEGORY':
                const category = parsed.category || 'бензин';
                showCategoryComparison(category);
                const compMsg = `Отображаю сравнение расходов на категорию ${category}.`;
                showToast(compMsg, 'info');
                voiceEngine.speak(compMsg);
                break;

            case 'QUERY_CATEGORY_EXPENSE':
                const targetCat = parsed.category;
                const totals = calculateCategoryTotals();
                const amount = totals[targetCat] || 0;
                const qMsg = `Расходы на категорию ${targetCat} составляют ${amount} долларов.`;
                showToast(qMsg, 'info');
                voiceEngine.speak(qMsg);
                break;

            case 'EXPORT_REPORT':
                FinanceExporter.exportToPDF(transactions, analyticsData);
                voiceEngine.speak('Формирую и подготавливаю PDF отчёт.');
                break;

            case 'SHOW_CHART':
                document.querySelector('.dashboard-grid').scrollIntoView({ behavior: 'smooth' });
                voiceEngine.speak('Показываю графики доходов и расходов.');
                break;

            default:
                const fallbackMsg = `Понял команду: "${rawText}". Пожалуйста, уточните сумму и категорию.`;
                showToast(fallbackMsg, 'info');
                voiceEngine.speak('Не удалось распознать сумму. Повторите команду, указав сумму.');
                break;
        }
    }

    /**
     * API & Persistence Functions
     */
    async function loadData() {
        try {
            const res = await fetch('/api/transactions');
            if (res.ok) {
                const json = await res.json();
                transactions = json.data || [];
            } else {
                transactions = JSON.parse(localStorage.getItem('vf_txs') || '[]');
            }
        } catch (e) {
            console.warn('[App] Server unreachable, using local storage.');
            transactions = JSON.parse(localStorage.getItem('vf_txs') || '[]');
        }
        populateFilterOptions();
        parseQueryParameters();
        filterAndRender();
    }

    async function addTransaction(txData) {
        let createdTx = null;
        try {
            const res = await fetch('/api/transactions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(txData)
            });
            if (res.ok) {
                const json = await res.json();
                createdTx = json.data;
            }
        } catch (e) {
            console.warn('[App] Server error, saving locally');
        }

        if (!createdTx) {
            createdTx = {
                id: Date.now(),
                ...txData,
                date: new Date().toISOString().split('T')[0]
            };
        }

        transactions.unshift(createdTx);
        localStorage.setItem('vf_txs', JSON.stringify(transactions));
        populateFilterOptions();
        filterAndRender();
        return createdTx;
    }

    async function deleteTransaction(id) {
        try {
            await fetch(`/api/transactions/${id}`, { method: 'DELETE' });
        } catch (e) {}

        transactions = transactions.filter(t => t.id !== id);
        localStorage.setItem('vf_txs', JSON.stringify(transactions));
        populateFilterOptions();
        filterAndRender();
        showToast('Запись удалена', 'info');
    }

    function updateUI(dataList = transactions) {
        // Calculate Totals
        let income = 0;
        let expense = 0;

        dataList.forEach(t => {
            const val = parseFloat(t.amount) || 0;
            if (t.type === 'income') income += val;
            else expense += val;
        });

        const balance = income - expense;
        const ratio = expense > 0 ? (income / expense).toFixed(1) : (income > 0 ? income.toFixed(1) : 0);

        analyticsData = { income, expense, balance, ratio };

        // Update Metrics
        metricIncome.innerText = `$${income.toLocaleString()}`;
        metricExpense.innerText = `$${expense.toLocaleString()}`;
        metricBalance.innerText = `$${balance.toLocaleString()}`;
        metricRatio.innerText = `${ratio}x`;

        if (ratio >= 1.5) metricRatioText.innerText = 'Отличный уровень сбережений!';
        else if (ratio >= 1.0) metricRatioText.innerText = 'Доходы пока покрывают расходы';
        else metricRatioText.innerText = 'Внимание: расходы превышают доходы';

        // Render Transactions List
        txCount.innerText = `${dataList.length} записей`;
        if (dataList.length === 0) {
            txList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon"><i class="fa-solid fa-microphone-slash"></i></div>
                    <p>Операций пока нет. Скажите команду микрофону!</p>
                </div>
            `;
        } else {
            txList.innerHTML = dataList.map(t => `
                <div class="tx-item">
                    <div class="tx-left">
                        <div class="tx-icon ${t.type === 'income' ? 'icon-income' : 'icon-expense'}">
                            <i class="fa-solid ${t.type === 'income' ? 'fa-arrow-down' : 'fa-arrow-up'}"></i>
                        </div>
                        <div>
                            <div class="tx-title">${t.category}</div>
                            <div class="tx-meta">${t.date} ${t.description ? '• ' + t.description : ''}</div>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center;">
                        <span class="tx-amount ${t.type}">
                            ${t.type === 'income' ? '+' : '-'}$${t.amount}
                        </span>
                        <button class="tx-delete-btn" onclick="deleteTxHandler(${t.id})" title="Удалить">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        // Render Category Charts
        const categoryTotals = calculateCategoryTotals(dataList);
        charts.renderCategoryChart('categoryChart', categoryTotals);

        // Render Trend Chart
        const monthlyData = calculateMonthlyTrends(dataList);
        charts.renderTrendChart('trendChart', monthlyData);
    }

    function calculateCategoryTotals(dataList = transactions) {
        const totals = {};
        dataList.filter(t => t.type === 'expense').forEach(t => {
            const cat = t.category || 'прочее';
            totals[cat] = (totals[cat] || 0) + (parseFloat(t.amount) || 0);
        });
        return totals;
    }

    function calculateMonthlyTrends(dataList = transactions) {
        const monthsMap = {};
        const monthNames = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];

        dataList.forEach(t => {
            const dateObj = new Date(t.date || Date.now());
            const mKey = `${monthNames[dateObj.getMonth()]}`;
            if (!monthsMap[mKey]) monthsMap[mKey] = { month: mKey, income: 0, expense: 0 };
            
            if (t.type === 'income') monthsMap[mKey].income += parseFloat(t.amount) || 0;
            else monthsMap[mKey].expense += parseFloat(t.amount) || 0;
        });

        const list = Object.values(monthsMap);
        return list.length > 0 ? list : [
            { month: 'Текущий', income: analyticsData.income, expense: analyticsData.expense }
        ];
    }

    function showCategoryComparison(categoryName) {
        compareCard.style.display = 'block';
        const sampleData = [
            { label: '2 мес назад', value: Math.round(Math.random() * 100 + 50) },
            { label: 'Прошлый месяц', value: Math.round(Math.random() * 150 + 80) },
            { label: 'Текущий месяц', value: calculateCategoryTotals()[categoryName] || 50 }
        ];
        charts.renderCompareChart('compareChart', categoryName, sampleData);
    }

    function populateFilterOptions() {
        if (!filterMonthEl || !filterCategoryEl) return;
        
        const prevMonth = filterMonthEl.value;
        const prevCategory = filterCategoryEl.value;
        
        filterMonthEl.innerHTML = '<option value="all">Все месяцы</option>';
        filterCategoryEl.innerHTML = '<option value="all">Все категории</option>';
        
        const uniqueMonths = {};
        const monthDisplayNames = {
            '01': 'Январь', '02': 'Февраль', '03': 'Март', '04': 'Апрель',
            '05': 'Май', '06': 'Июнь', '07': 'Июль', '08': 'Август',
            '09': 'Сентябрь', '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь'
        };
        
        const uniqueCategories = new Set();
        
        transactions.forEach(t => {
            if (t.date && t.date.length >= 7) {
                const yyyy_mm = t.date.substring(0, 7);
                const [year, month] = yyyy_mm.split('-');
                if (monthDisplayNames[month]) {
                    const displayName = `${monthDisplayNames[month]} ${year}`;
                    uniqueMonths[yyyy_mm] = displayName;
                }
            }
            if (t.category) {
                uniqueCategories.add(t.category.toLowerCase());
            }
        });
        
        const sortedMonths = Object.keys(uniqueMonths).sort().reverse();
        sortedMonths.forEach(yyyy_mm => {
            const opt = document.createElement('option');
            opt.value = yyyy_mm;
            opt.textContent = uniqueMonths[yyyy_mm];
            filterMonthEl.appendChild(opt);
        });
        
        const sortedCategories = Array.from(uniqueCategories).sort();
        sortedCategories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            filterCategoryEl.appendChild(opt);
        });
        
        if (Array.from(filterMonthEl.options).some(o => o.value === prevMonth)) {
            filterMonthEl.value = prevMonth;
        }
        if (Array.from(filterCategoryEl.options).some(o => o.value === prevCategory)) {
            filterCategoryEl.value = prevCategory;
        }
    }

    function parseQueryParameters() {
        const params = new URLSearchParams(window.location.search);
        
        const qCategory = params.get('category');
        if (qCategory && filterCategoryEl) {
            filterCategory = qCategory.toLowerCase();
            // Add custom category option to dropdown if it's not present yet
            const hasOption = Array.from(filterCategoryEl.options).some(o => o.value === filterCategory);
            if (!hasOption) {
                const opt = document.createElement('option');
                opt.value = filterCategory;
                opt.textContent = filterCategory;
                filterCategoryEl.appendChild(opt);
            }
            filterCategoryEl.value = filterCategory;
        }
        
        const qMonthsCount = params.get('months');
        if (qMonthsCount) {
            const monthsVal = parseInt(qMonthsCount);
            if (!isNaN(monthsVal)) {
                const cutoff = new Date();
                cutoff.setMonth(cutoff.getMonth() - monthsVal);
                filterDateCutoff = cutoff.toISOString().substring(0, 10);
            }
        }
    }

    function filterAndRender() {
        let filtered = transactions;
        
        if (filterCategory && filterCategory !== 'all') {
            filtered = filtered.filter(t => (t.category || '').toLowerCase() === filterCategory.toLowerCase());
        }
        
        if (filterMonth && filterMonth !== 'all') {
            filtered = filtered.filter(t => t.date && t.date.substring(0, 7) === filterMonth);
        }
        
        if (filterDateCutoff) {
            filtered = filtered.filter(t => t.date && t.date >= filterDateCutoff);
        }
        
        if (filterSearch) {
            const query = filterSearch.toLowerCase();
            filtered = filtered.filter(t => 
                (t.description || '').toLowerCase().includes(query) || 
                (t.category || '').toLowerCase().includes(query)
            );
        }
        
        updateUI(filtered);
    }

    if (filterMonthEl) {
        filterMonthEl.addEventListener('change', (e) => {
            filterMonth = e.target.value;
            filterDateCutoff = null; // Clear URL query constraints on manual interaction
            filterAndRender();
        });
    }
    if (filterCategoryEl) {
        filterCategoryEl.addEventListener('change', (e) => {
            filterCategory = e.target.value;
            filterAndRender();
        });
    }
    if (filterSearchEl) {
        filterSearchEl.addEventListener('input', (e) => {
            filterSearch = e.target.value;
            filterAndRender();
        });
    }

    // Modal & Form Handlers
    btnManualAdd.addEventListener('click', () => addModal.classList.add('active'));
    btnCloseModal.addEventListener('click', () => addModal.classList.remove('active'));
    btnCloseCompare.addEventListener('click', () => compareCard.style.display = 'none');

    addTxForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const type = document.getElementById('txType').value;
        const amount = parseFloat(document.getElementById('txAmount').value);
        const category = document.getElementById('txCategory').value;
        const description = document.getElementById('txDesc').value;

        if (amount > 0) {
            await addTransaction({ type, amount, currency: 'USD', category, description });
            addModal.classList.remove('active');
            addTxForm.reset();
            showToast('Запись успешно добавлена', 'success');
        }
    });

    // Exporter Handlers
    btnExportCSV.addEventListener('click', () => FinanceExporter.exportToCSV(transactions));
    btnExportPDF.addEventListener('click', () => FinanceExporter.exportToPDF(transactions, analyticsData));

    // Global helper for inline onclick
    window.deleteTxHandler = (id) => deleteTransaction(id);

    // Toast Function
    function showToast(msg, type = 'info') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<i class="fa-solid fa-circle-info"></i> <span>${msg}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // Initial Data Load
    loadData();
});
