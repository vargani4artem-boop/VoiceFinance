/**
 * Exporter Module for VoiceFinance
 * Handles exporting transactions to CSV and printable styled PDF report.
 */

class FinanceExporter {
    /**
     * Download CSV File
     */
    static exportToCSV(transactions, filename = 'voicefinance_transactions.csv') {
        if (!transactions || transactions.length === 0) {
            alert('Нет данных для экспорта');
            return;
        }

        const headers = ['ID', 'Тип', 'Сумма', 'Валюта', 'Категория', 'Описание', 'Голосовая команда', 'Дата'];
        const rows = transactions.map(t => [
            t.id || '',
            t.type === 'income' ? 'Доход' : 'Расход',
            t.amount,
            t.currency || 'USD',
            `"${(t.category || '').replace(/"/g, '""')}"`,
            `"${(t.description || '').replace(/"/g, '""')}"`,
            `"${(t.raw_voice || '').replace(/"/g, '""')}"`,
            t.date
        ]);

        const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    /**
     * Generate & Print PDF Financial Report
     */
    static exportToPDF(transactions, analytics) {
        if (!transactions || transactions.length === 0) {
            alert('Нет данных для отчёта');
            return;
        }

        const printWindow = window.open('', '_blank');
        const nowStr = new Date().toLocaleDateString('ru-RU');

        const rowsHtml = transactions.map(t => `
            <tr>
                <td>${t.date}</td>
                <td><span class="badge ${t.type}">${t.type === 'income' ? 'Доход' : 'Расход'}</span></td>
                <td><strong>$${t.amount}</strong></td>
                <td>${t.category}</td>
                <td>${t.description || t.raw_voice || '-'}</td>
            </tr>
        `).join('');

        const htmlContent = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>Финансовый отчёт VoiceFinance - ${nowStr}</title>
            <style>
                body { font-family: sans-serif; color: #1E293B; margin: 2rem; }
                h1 { color: #6366F1; display: flex; align-items: center; justify-content: space-between; }
                .meta { color: #64748B; font-size: 0.9rem; margin-bottom: 2rem; border-bottom: 2px solid #E2E8F0; padding-bottom: 1rem; }
                .summary-box { display: flex; gap: 1.5rem; margin-bottom: 2rem; }
                .card { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 1rem; flex: 1; text-align: center; }
                .card h3 { margin: 0; font-size: 0.85rem; color: #64748B; text-transform: uppercase; }
                .card p { margin: 0.5rem 0 0 0; font-size: 1.5rem; font-weight: bold; }
                .income { color: #10B981; }
                .expense { color: #EF4444; }
                table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
                th, td { border: 1px solid #E2E8F0; padding: 0.75rem; text-align: left; font-size: 0.9rem; }
                th { background: #F1F5F9; font-weight: 600; }
                .badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }
                .badge.income { background: #D1FAE5; color: #065F46; }
                .badge.expense { background: #FEE2E2; color: #991B1B; }
                @media print { button { display: none; } }
            </style>
        </head>
        <body>
            <h1>VoiceFinance <span>Финансовый отчёт</span></h1>
            <div class="meta">Дата формирования: ${nowStr} | Всего операций: ${transactions.length}</div>
            
            <div class="summary-box">
                <div class="card"><h3>Доходы</h3><p class="income">$${analytics.income || 0}</p></div>
                <div class="card"><h3>Расходы</h3><p class="expense">$${analytics.expense || 0}</p></div>
                <div class="card"><h3>Баланс</h3><p>$${analytics.balance || 0}</p></div>
                <div class="card"><h3>Соотношение</h3><p>${analytics.ratio || 0}x</p></div>
            </div>

            <h2>История операций</h2>
            <table>
                <thead>
                    <tr>
                        <th>Дата</th>
                        <th>Тип</th>
                        <th>Сумма</th>
                        <th>Категория</th>
                        <th>Описание</th>
                    </tr>
                </thead>
                <tbody>
                    ${rowsHtml}
                </tbody>
            </table>

            <script>
                window.onload = function() { window.print(); }
            </script>
        </body>
        </html>
        `;

        printWindow.document.write(htmlContent);
        printWindow.document.close();
    }
}
