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
            if (voiceStatus && voiceStatus.innerText.startsWith('✅') && (text === 'Нажмите микрофон для записи' || text === 'Нажмите для активации')) {
                // Keep the success receipt text visible until next recording starts
                if (!listening) {
                    voiceBtn.classList.remove('listening');
                    voiceBtnIcon.className = 'fa-solid fa-microphone';
                }
                return;
            }
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
        if (!voiceEngine.isListening && voiceStatus && voiceStatus.innerText.startsWith('✅')) {
            voiceStatus.innerText = 'Слушаю...';
        }
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

                const amtStr = `$${parsed.amount.toFixed(2)}`;
                const displayMsg = `${amtStr} на ${parsed.description || parsed.category} внесены в раздел '${parsed.category}'`;
                showToast(`✅ ${displayMsg}`, 'success');
                if (voiceStatus) {
                    voiceStatus.innerText = `✅ ${displayMsg}`;
                }
                voiceEngine.speak(displayMsg);
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
        await loadAccounts();
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

    function updateLastTxWidget() {
        const container = document.getElementById('lastTxContainer');
        const textEl = document.getElementById('lastTxText');
        if (!container || !textEl) return;

        if (transactions.length > 0) {
            const last = transactions[0];
            const typeLabel = last.type === 'income' ? 'Доход 🟢' : 'Расход 🔴';
            const amtStr = parseFloat(last.amount).toFixed(2);
            textEl.innerHTML = `<span style="color: ${last.type === 'income' ? '#10B981' : '#EF4444'}; font-weight: 800;">${typeLabel} $${amtStr}</span> — ${last.category || last.description || 'прочее'}`;
            container.style.opacity = '1';
            container.style.transform = 'translateY(0)';
        } else {
            textEl.innerText = 'Нет записей';
            container.style.opacity = '0.5';
            container.style.transform = 'translateY(0)';
        }
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

        // Update Last Transaction Widget on main screen
        updateLastTxWidget();
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
            const normQ = qCategory.toLowerCase();
            
            // Fuzzy match against existing options
            let matchedOptionValue = 'all';
            Array.from(filterCategoryEl.options).forEach(opt => {
                const optVal = opt.value.toLowerCase();
                if (optVal === 'all') return;
                
                if (optVal.includes(normQ) || normQ.includes(optVal)) {
                    matchedOptionValue = opt.value;
                } else {
                    const prefixDb = optVal.substring(0, 4);
                    const prefixQ = normQ.substring(0, 4);
                    if (prefixDb.length >= 3 && prefixQ.length >= 3 && (optVal.includes(prefixQ) || normQ.includes(prefixDb))) {
                        matchedOptionValue = opt.value;
                    }
                }
            });
            
            if (matchedOptionValue !== 'all') {
                filterCategory = matchedOptionValue;
                filterCategoryEl.value = matchedOptionValue;
            } else {
                filterCategory = normQ;
                const opt = document.createElement('option');
                opt.value = filterCategory;
                opt.textContent = filterCategory;
                filterCategoryEl.appendChild(opt);
                filterCategoryEl.value = filterCategory;
            }
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
            filtered = filtered.filter(t => {
                const dbCat = (t.category || '').toLowerCase();
                const qCat = filterCategory.toLowerCase();
                if (dbCat === qCat || dbCat.includes(qCat) || qCat.includes(dbCat)) return true;
                const prefixDb = dbCat.substring(0, 4);
                const prefixQ = qCat.substring(0, 4);
                if (prefixDb.length >= 3 && prefixQ.length >= 3 && (dbCat.includes(prefixQ) || qCat.includes(prefixDb))) {
                    return true;
                }
                return false;
            });
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

    // Screen Toggle Event Listeners
    const btnOpenReports = document.getElementById('btnOpenReports');
    const btnCloseReports = document.getElementById('btnCloseReports');
    const recorderScreen = document.getElementById('recorderScreen');
    const reportsScreen = document.getElementById('reportsScreen');

    if (btnOpenReports && btnCloseReports && recorderScreen && reportsScreen) {
        btnOpenReports.addEventListener('click', () => {
            recorderScreen.classList.remove('active');
            reportsScreen.classList.add('active');
        });
        btnCloseReports.addEventListener('click', () => {
            reportsScreen.classList.remove('active');
            recorderScreen.classList.add('active');
        });
    }

    // Modal & Form Handlers
    btnManualAdd.addEventListener('click', () => addModal.classList.add('active'));
    btnCloseModal.addEventListener('click', () => addModal.classList.remove('active'));
    btnCloseCompare.addEventListener('click', () => compareCard.style.display = 'none');

    addTxForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const type = document.querySelector('input[name="txType"]:checked').value;
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

    // Accounts rendering and editing
    let accounts = [];

    async function loadAccounts() {
        try {
            const res = await fetch('/api/accounts');
            if (res.ok) {
                const json = await res.json();
                accounts = json.data || [];
                renderAccounts();
            }
        } catch (e) {
            console.error('[App] Failed to load accounts:', e);
        }
    }

    function renderAccounts() {
        const accountsGrid = document.getElementById('accountsGrid');
        if (!accountsGrid) return;
        
        accountsGrid.innerHTML = '';
        
        // Convert accounts balance to CAD for unified Net Worth estimation
        // CAD = 1.0, UAH = 0.033, USD = 1.35
        let totalAssetsCAD = 0.0;
        let totalDebtsCAD = 0.0;
        
        accounts.forEach(acct => {
            const balance = acct.balance || 0;
            const currency = acct.currency || 'USD';
            const type = acct.type || 'asset';
            
            let valCAD = balance;
            if (currency === 'UAH') valCAD = balance * 0.033;
            else if (currency === 'USD') valCAD = balance * 1.35;
            
            if (type === 'asset') {
                totalAssetsCAD += valCAD;
            } else {
                totalDebtsCAD += valCAD;
            }
            
            let iconClass = 'fa-solid fa-wallet';
            if (acct.name.toLowerCase().includes('сберегательн') || acct.name.toLowerCase().includes('savings')) {
                iconClass = 'fa-solid fa-piggy-bank';
            } else if (acct.name.toLowerCase().includes('interactive') || acct.name.toLowerCase().includes('broker')) {
                iconClass = 'fa-solid fa-arrow-trend-up';
            } else if (acct.name.toLowerCase().includes('карт')) {
                iconClass = 'fa-solid fa-credit-card';
            }
            
            let currencySymbol = '$';
            if (currency === 'UAH') currencySymbol = '₴';
            else if (currency === 'CAD') currencySymbol = 'C$';
            
            const card = document.createElement('div');
            card.className = `account-card ${type}`;
            card.style.background = 'rgba(255, 255, 255, 0.03)';
            card.style.border = '1px solid rgba(255, 255, 255, 0.05)';
            card.style.borderRadius = '12px';
            card.style.padding = '1.25rem';
            card.style.position = 'relative';
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.justifyContent = 'space-between';
            card.style.minHeight = '100px';
            card.style.transition = 'transform 0.2s, box-shadow 0.2s';
            
            if (type === 'asset') {
                card.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
                        <div style="background: rgba(16, 185, 129, 0.1); color: #10B981; width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1.1rem;">
                            <i class="${iconClass}"></i>
                        </div>
                        <div>
                            <div style="font-size: 0.85rem; color: var(--text-muted); font-weight: 500;">${acct.name}</div>
                            <div style="font-size: 1.15rem; font-weight: 700; color: #10B981;">${currencySymbol} ${balance.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                        </div>
                    </div>
                    <button class="btn-edit-account" data-id="${acct.id}" style="position: absolute; top: 0.75rem; right: 0.75rem; background: none; border: none; color: var(--text-muted); cursor: pointer; transition: color 0.2s; font-size: 0.85rem;"><i class="fa-solid fa-pencil"></i></button>
                `;
            } else {
                const limit = acct.credit_limit || 0;
                const remaining = acct.credit_remaining || 0;
                const used = balance;
                const utilPercent = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
                const isHighUtil = utilPercent > 80;
                const progressColor = isHighUtil ? '#EF4444' : '#6366F1';
                
                card.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
                        <div style="background: rgba(239, 68, 68, 0.1); color: #EF4444; width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1.1rem;">
                            <i class="${iconClass}"></i>
                        </div>
                        <div>
                            <div style="font-size: 0.85rem; color: var(--text-muted); font-weight: 500;">${acct.name}</div>
                            <div style="font-size: 1.15rem; font-weight: 700; color: #EF4444;">${currencySymbol} ${used.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})} <span style="font-size: 0.8rem; font-weight: 500; color: var(--text-muted);">долг</span></div>
                        </div>
                    </div>
                    <div style="margin-top: 0.5rem;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                            <span>Использовано: ${utilPercent.toFixed(0)}%</span>
                            <span>Осталось: ${currencySymbol}${remaining.toLocaleString('ru-RU', {maximumFractionDigits: 0})}</span>
                        </div>
                        <div style="width: 100%; height: 6px; background: rgba(255, 255, 255, 0.08); border-radius: 3px; overflow: hidden;">
                            <div style="width: ${utilPercent}%; height: 100%; background: ${progressColor}; border-radius: 3px;"></div>
                        </div>
                    </div>
                    <button class="btn-edit-account" data-id="${acct.id}" style="position: absolute; top: 0.75rem; right: 0.75rem; background: none; border: none; color: var(--text-muted); cursor: pointer; transition: color 0.2s; font-size: 0.85rem;"><i class="fa-solid fa-pencil"></i></button>
                `;
            }
            accountsGrid.appendChild(card);
        });
        
        const netWorthValEl = document.getElementById('netWorthValue');
        if (netWorthValEl) {
            const netWorthCAD = totalAssetsCAD - totalDebtsCAD;
            const sign = netWorthCAD < 0 ? '-' : '';
            const absValue = Math.abs(netWorthCAD);
            netWorthValEl.innerText = `${sign}C$ ${absValue.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            netWorthValEl.style.color = netWorthCAD >= 0 ? '#10B981' : '#EF4444';
        }
        
        document.querySelectorAll('.btn-edit-account').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const target = e.currentTarget;
                const acctId = parseInt(target.getAttribute('data-id'));
                const acct = accounts.find(a => a.id === acctId);
                if (acct) {
                    openAccountModal(acct);
                }
            });
        });
    }

    function openAccountModal(acct) {
        const modal = document.getElementById('accountModal');
        const title = document.getElementById('accountModalTitle');
        const idInput = document.getElementById('editAccountId');
        const stdInputWrapper = document.getElementById('standardBalanceInput');
        const creditInputsWrapper = document.getElementById('creditLimitInputs');
        
        idInput.value = acct.id;
        title.innerText = `Редактировать счет: ${acct.name}`;
        
        if (acct.type === 'debt') {
            stdInputWrapper.style.display = 'none';
            creditInputsWrapper.style.display = 'flex';
            document.getElementById('editCreditLimit').value = acct.credit_limit || 0;
            document.getElementById('editCreditRemaining').value = acct.credit_remaining || 0;
        } else {
            stdInputWrapper.style.display = 'block';
            creditInputsWrapper.style.display = 'none';
            document.getElementById('editAccountBalance').value = acct.balance || 0;
        }
        
        modal.classList.add('active');
    }

    const closeAccountModalBtn = document.getElementById('closeAccountModal');
    const saveAccountBtn = document.getElementById('saveAccountBtn');
    const accountModal = document.getElementById('accountModal');
    
    if (closeAccountModalBtn) {
        closeAccountModalBtn.addEventListener('click', () => accountModal.classList.remove('active'));
    }
    
    if (saveAccountBtn) {
        saveAccountBtn.addEventListener('click', async () => {
            const id = parseInt(document.getElementById('editAccountId').value);
            const balanceInput = document.getElementById('editAccountBalance').value;
            const creditLimitInput = document.getElementById('editCreditLimit').value;
            const creditRemainingInput = document.getElementById('editCreditRemaining').value;
            
            const payload = { id };
            const acct = accounts.find(a => a.id === id);
            
            if (acct.type === 'debt') {
                payload.credit_limit = parseFloat(creditLimitInput) || 0;
                payload.credit_remaining = parseFloat(creditRemainingInput) || 0;
            } else {
                payload.balance = parseFloat(balanceInput) || 0;
            }
            
            try {
                const res = await fetch('/api/accounts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showToast('Счет успешно обновлен', 'success');
                    accountModal.classList.remove('active');
                    await loadAccounts();
                } else {
                    showToast('Ошибка при обновлении счета', 'danger');
                }
            } catch (e) {
                showToast('Ошибка сети', 'danger');
            }
        });
    }

    // Quick Voice Action Buttons Event Listeners
    const btnQuickExpenses = document.getElementById('btnQuickExpenses');
    const btnQuickCategories = document.getElementById('btnQuickCategories');
    const btnQuickIncomes = document.getElementById('btnQuickIncomes');
    const btnQuickDifference = document.getElementById('btnQuickDifference');

    function getFilteredMetrics() {
        let inc = 0;
        let exp = 0;
        const catMap = {};
        
        let filtered = [...transactions];
        if (filterMonth !== 'all') {
            filtered = filtered.filter(t => t.date && t.date.startsWith(filterMonth));
        }
        if (filterCategory !== 'all') {
            filtered = filtered.filter(t => t.category === filterCategory);
        }
        if (filterSearch) {
            const query = filterSearch.toLowerCase();
            filtered = filtered.filter(t => 
                (t.description || '').toLowerCase().includes(query) || 
                (t.category || '').toLowerCase().includes(query)
            );
        }

        filtered.forEach(t => {
            const amt = parseFloat(t.amount || 0);
            if (t.type === 'income') {
                inc += amt;
            } else {
                exp += amt;
                catMap[t.category] = (catMap[t.category] || 0) + amt;
            }
        });

        return { income: inc, expense: exp, categories: catMap };
    }

    if (btnQuickExpenses) {
        btnQuickExpenses.addEventListener('click', () => {
            const m = getFilteredMetrics();
            const speechText = `Сумма расходов за этот период составляет ${m.expense.toFixed(0)} долларов.`;
            showToast(speechText, 'info');
            voiceEngine.speak(speechText);
        });
    }

    if (btnQuickCategories) {
        btnQuickCategories.addEventListener('click', () => {
            const m = getFilteredMetrics();
            const sortedCats = Object.entries(m.categories).sort((a, b) => b[1] - a[1]);
            if (sortedCats.length === 0) {
                const noDataText = "Расходы по категориям отсутствуют.";
                showToast(noDataText, 'info');
                voiceEngine.speak(noDataText);
                return;
            }
            const breakdown = sortedCats.map(c => `${c[0]}: ${c[1].toFixed(0)} долларов`).join(', ');
            const speechText = `Расходы по категориям: ${breakdown}.`;
            showToast(speechText, 'info');
            const shortBreakdown = sortedCats.slice(0, 3).map(c => `${c[0]} — ${c[1].toFixed(0)} долларов`).join(', ');
            voiceEngine.speak(`Основные статьи расходов: ${shortBreakdown}`);
        });
    }

    if (btnQuickIncomes) {
        btnQuickIncomes.addEventListener('click', () => {
            const m = getFilteredMetrics();
            const speechText = `Сумма ваших доходов за этот период составляет ${m.income.toFixed(0)} долларов.`;
            showToast(speechText, 'info');
            voiceEngine.speak(speechText);
        });
    }

    if (btnQuickDifference) {
        btnQuickDifference.addEventListener('click', () => {
            const m = getFilteredMetrics();
            const diff = m.income - m.expense;
            let speechText = '';
            if (diff >= 0) {
                speechText = `Разница положительная: профицит бюджета составляет ${diff.toFixed(0)} долларов.`;
            } else {
                speechText = `Разница отрицательная: дефицит бюджета составляет ${Math.abs(diff).toFixed(0)} долларов.`;
            }
            showToast(speechText, 'info');
            voiceEngine.speak(speechText);
        });
    }

    // Toast Function
    function showToast(msg, type = 'info') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<i class="fa-solid fa-circle-info"></i> <span>${msg}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // Initial Data Load & Background real-time polling (every 3 seconds)
    loadData();
    setInterval(loadData, 3000);
});
