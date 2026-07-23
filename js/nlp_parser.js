/**
 * Russian NLP / NLU Parser for VoiceFinance
 * Handles intent detection, entity extraction (amounts, currencies, categories, dates)
 * and natural language queries.
 */

class NLUParser {
    constructor() {
        this.numberMap = {
            'ноль': 0, 'один': 1, 'одна': 1, 'одно': 1, 'два': 2, 'две': 2, 'три': 3,
            'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9,
            'десять': 10, 'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13,
            'четырнадцать': 14, 'пятнадцать': 15, 'шестнадцать': 16, 'семнадцать': 17,
            'восемнадцать': 18, 'девятнадцать': 19, 'двадцать': 20, 'тридцать': 30,
            'сорок': 40, 'пятьдесят': 50, 'шестьдесят': 60, 'семьдесят': 70,
            'восемьдесят': 80, 'девяносто': 90, 'сто': 100, 'двести': 200,
            'триста': 300, 'четыреста': 400, 'пятьсот': 500, 'шестьсот': 600,
            'семьсот': 700, 'восемьсот': 800, 'девятьсот': 900, 'тысяча': 1000,
            'тысячи': 1000, 'тысяч': 1000, 'миллион': 1000000, 'миллиона': 1000000, 'миллионов': 1000000
        };

        this.currencyMap = {
            'доллар': 'USD', 'доллара': 'USD', 'долларов': 'USD', 'баксов': 'USD', 'бакс': 'USD', '$': 'USD',
            'рубль': 'RUB', 'рубля': 'RUB', 'рублей': 'RUB', 'руб': 'RUB', '₽': 'RUB',
            'евро': 'EUR', '€': 'EUR',
            'тенге': 'KZT', 'гривна': 'UAH', 'юань': 'CNY'
        };

        this.categoryKeywords = {
            'продукты': ['продукты', 'продукт', 'еда', 'супермаркет', 'магазин', 'покупки', 'ашан', 'пятерочка', 'магнит', 'макдоналдс'],
            'бензин': ['бензин', 'заправка', 'топливо', 'газпром', 'лукойл', 'роснефть', 'аи95', 'аи92'],
            'транспорт': ['транспорт', 'такси', 'метро', 'автобус', 'проезд', 'билет', 'яндекс такси', 'убер'],
            'коммунальные': ['коммуналка', 'коммунальные', 'свет', 'вода', 'газ', 'интернет', 'квартплата', 'жилье'],
            'кредиты': ['кредит', 'ипотека', 'долг', 'заем', 'займ', 'банк', 'рассрочка'],
            'развлечения': ['развлечения', 'кино', 'театр', 'концерт', 'игры', 'паб', 'клуб', 'боулинг', 'отдых'],
            'бизнес': ['бизнес', 'налоги', 'сервер', 'реклама', 'маркетинг', 'софт'],
            'кафе и рестораны': ['кафе', 'ресторан', 'кофе', 'кофейня', 'обед', 'ужин', 'доставка', 'пицца', 'суши'],
            'здоровье': ['здоровье', 'аптека', 'врач', 'лекарства', 'анализы', 'стоматолог', 'спортзал', 'фитнес'],
            'зарплата': ['зарплата', 'аванс', 'зп', 'оклад', 'премия'],
            'фриланс': ['фриланс', 'проект', 'заказ', 'клиент', 'гонорар'],
            'инвестиции': ['инвестиции', 'акции', 'дивиденды', 'крипта', 'проценты', 'вклад'],
            'подарок': ['подарок', 'подарки', 'пожертвование', 'чаевые']
        };
    }

    /**
     * Parse text into number
     */
    parseWordsToNumber(text) {
        // Try direct regex first for digits
        const digitMatch = text.match(/\b\d+([.,]\d+)?\b/);
        if (digitMatch) {
            return parseFloat(digitMatch[0].replace(',', '.'));
        }

        // Parse Russian number words
        const words = text.toLowerCase().split(/\s+/);
        let total = 0;
        let current = 0;

        for (const w of words) {
            if (this.numberMap[w] !== undefined) {
                const val = this.numberMap[w];
                if (val === 1000 || val === 1000000) {
                    current = (current === 0 ? 1 : current) * val;
                    total += current;
                    current = 0;
                } else {
                    current += val;
                }
            }
        }
        total += current;
        return total > 0 ? total : null;
    }

    /**
     * Extract currency
     */
    extractCurrency(text) {
        const words = text.toLowerCase().split(/\s+/);
        for (const w of words) {
            if (this.currencyMap[w]) {
                return this.currencyMap[w];
            }
        }
        return 'USD';
    }

    /**
     * Match category from text
     */
    matchCategory(text, defaultType = 'expense') {
        const lower = text.toLowerCase();
        for (const [catName, keywords] of Object.entries(this.categoryKeywords)) {
            for (const kw of keywords) {
                if (lower.includes(kw)) {
                    return catName;
                }
            }
        }
        return defaultType === 'income' ? 'зарплата' : 'прочее';
    }

    /**
     * Main intent parser
     */
    parse(text) {
        const clean = text.trim().toLowerCase();
        
        // 1. Check Analytics / Queries Intent
        if (clean.includes('во сколько раз') && (clean.includes('больше') || clean.includes('меньше'))) {
            return { intent: 'QUERY_RATIO', raw: text };
        }
        if (clean.includes('топ расход') || clean.includes('главные расходы') || clean.includes('топ по категориям')) {
            return { intent: 'QUERY_TOP_EXPENSE', raw: text };
        }
        if (clean.includes('сравни') || clean.includes('сравнение')) {
            const cat = this.matchCategory(clean);
            return { intent: 'COMPARE_CATEGORY', category: cat, months: 3, raw: text };
        }
        if (clean.includes('график') || clean.includes('нарисуй') || clean.includes('покажи график')) {
            return { intent: 'SHOW_CHART', raw: text };
        }
        if (clean.includes('выгрузи') || clean.includes('скачай') || clean.includes('отчет') || clean.includes('отчёт')) {
            return { intent: 'EXPORT_REPORT', raw: text };
        }
        if (clean.includes('покажи расходы') || clean.includes('расходы на') || clean.includes('сколько потратил')) {
            const cat = this.matchCategory(clean);
            return { intent: 'QUERY_CATEGORY_EXPENSE', category: cat, raw: text };
        }

        // 2. Transaction Insertion Intent
        const isIncome = clean.includes('доход') || clean.includes('получил') || clean.includes('приход') || clean.includes('плюс');
        const isExpense = clean.includes('расход') || clean.includes('потратил') || clean.includes('купил') || clean.includes('минус') || clean.includes('оплатил');

        const amount = this.parseWordsToNumber(clean);
        
        if (amount) {
            const type = isIncome ? 'income' : 'expense';
            const currency = this.extractCurrency(clean);
            const category = this.matchCategory(clean, type);

            return {
                intent: 'ADD_TRANSACTION',
                type: type,
                amount: amount,
                currency: currency,
                category: category,
                description: text,
                raw: text
            };
        }

        // Fallback unknown command
        return {
            intent: 'UNKNOWN',
            raw: text
        };
    }
}
