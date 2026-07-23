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
        updateUI();
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
        updateUI();
        return createdTx;
    }

    async function deleteTransaction(id) {
        try {
            await fetch(`/api/transactions/${id}`, { method: 'DELETE' });
        } catch (e) {}

        transactions = transactions.filter(t => t.id !== id);
        localStorage.setItem('vf_txs', JSON.stringify(transactions));
        updateUI();
        showToast('Запись удалена', 'info');
    }

    /**
     * UI Update Orchestrator
     */
    function updateUI() {
        // Calculate Totals
        let income = 0;
        let expense = 0;

        transactions.forEach(t => {
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
        txCount.innerText = `${transactions.length} записей`;
        if (transactions.length === 0) {
            txList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon"><i class="fa-solid fa-microphone-slash"></i></div>
                    <p>Операций пока нет. Скажите команду микрофону!</p>
                </div>
            `;
        } else {
            txList.innerHTML = transactions.map(t => `
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
        const categoryTotals = calculateCategoryTotals();
        charts.renderCategoryChart('categoryChart', categoryTotals);

        // Render Trend Chart
        const monthlyData = calculateMonthlyTrends();
        charts.renderTrendChart('trendChart', monthlyData);
    }

    function calculateCategoryTotals() {
        const totals = {};
        transactions.filter(t => t.type === 'expense').forEach(t => {
            const cat = t.category || 'прочее';
            totals[cat] = (totals[cat] || 0) + (parseFloat(t.amount) || 0);
        });
        return totals;
    }

    function calculateMonthlyTrends() {
        const monthsMap = {};
        const monthNames = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];

        transactions.forEach(t => {
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
