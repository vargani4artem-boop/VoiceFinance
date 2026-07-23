/**
 * Charts Engine for VoiceFinance
 * Uses Chart.js for rendering responsive, dark-mode financial charts.
 */

class FinanceCharts {
    constructor() {
        this.categoryChart = null;
        this.trendChart = null;
        this.compareChart = null;
        
        // Color palette for categories
        this.colors = [
            '#10B981', '#F59E0B', '#3B82F6', '#6366F1', '#EF4444', 
            '#EC4899', '#8B5CF6', '#F97316', '#06B6D4', '#14B8A6'
        ];
    }

    /**
     * Render or Update Category Expenses Doughnut Chart
     */
    renderCategoryChart(canvasId, categoryTotals) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const labels = Object.keys(categoryTotals);
        const data = Object.values(categoryTotals);

        if (this.categoryChart) {
            this.categoryChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        this.categoryChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels.length > 0 ? labels : ['Нет данных'],
                datasets: [{
                    data: data.length > 0 ? data : [1],
                    backgroundColor: data.length > 0 ? this.colors.slice(0, labels.length) : ['#334155'],
                    borderWidth: 2,
                    borderColor: '#0B0F19'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#94A3B8', font: { family: 'Plus Jakarta Sans', size: 11 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: $${ctx.raw}`
                        }
                    }
                },
                cutout: '65%'
            }
        });
    }

    /**
     * Render Monthly Income vs Expense Bar Chart
     */
    renderTrendChart(canvasId, monthlyData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const months = monthlyData.map(m => m.month);
        const incomes = monthlyData.map(m => m.income);
        const expenses = monthlyData.map(m => m.expense);

        if (this.trendChart) {
            this.trendChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        this.trendChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: months,
                datasets: [
                    {
                        label: 'Доходы',
                        data: incomes,
                        backgroundColor: 'rgba(16, 185, 129, 0.75)',
                        borderColor: '#10B981',
                        borderWidth: 1,
                        borderRadius: 6
                    },
                    {
                        label: 'Расходы',
                        data: expenses,
                        backgroundColor: 'rgba(239, 68, 68, 0.75)',
                        borderColor: '#EF4444',
                        borderWidth: 1,
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94A3B8', font: { family: 'Plus Jakarta Sans' } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94A3B8', font: { family: 'Plus Jakarta Sans' } }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { color: '#94A3B8', font: { family: 'Plus Jakarta Sans', size: 11 } }
                    }
                }
            }
        });
    }

    /**
     * Render Comparative Category Chart (e.g. for "сравни бензин за три месяца")
     */
    renderCompareChart(canvasId, categoryName, compareData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const labels = compareData.map(d => d.label);
        const values = compareData.map(d => d.value);

        if (this.compareChart) {
            this.compareChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        this.compareChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: `Динамика: ${categoryName}`,
                    data: values,
                    borderColor: '#8B5CF6',
                    backgroundColor: 'rgba(139, 92, 246, 0.15)',
                    fill: true,
                    tension: 0.35,
                    pointBackgroundColor: '#8B5CF6',
                    pointRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: '#94A3B8' } },
                    y: { ticks: { color: '#94A3B8' } }
                },
                plugins: {
                    legend: { labels: { color: '#F8FAFC' } }
                }
            }
        });
    }
}
