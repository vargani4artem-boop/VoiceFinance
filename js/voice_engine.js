/**
 * Voice Engine - Web Speech Recognition & Speech Synthesis
 * Supports Siri-like Wake Word ("Эй Финансы") & Realtime Audio Visualization
 */

class VoiceEngine {
    constructor(options = {}) {
        this.lang = options.lang || 'ru-RU';
        this.onCommandCallback = options.onCommand || null;
        this.onStatusChange = options.onStatusChange || null;
        
        this.recognition = null;
        this.isListening = false;
        this.wakeWordMode = false;
        this.synth = window.speechSynthesis;
        
        this.canvas = options.canvas || null;
        this.canvasCtx = this.canvas ? this.canvas.getContext('2d') : null;
        this.animFrameId = null;
        
        this.initRecognition();
    }

    initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn('SpeechRecognition is not supported in this browser.');
            return false;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = this.lang;

        this.recognition.onstart = () => {
            this.isListening = true;
            this.updateStatus('Слушаю...', true);
            this.startWaveformAnimation();
        };

        this.recognition.onend = () => {
            if (this.wakeWordMode) {
                // Restart continuously for Siri wake-word mode
                try {
                    this.recognition.start();
                } catch (e) {
                    this.isListening = false;
                    this.updateStatus('Нажмите для активации', false);
                    this.stopWaveformAnimation();
                }
            } else {
                this.isListening = false;
                this.updateStatus('Нажмите микрофон для записи', false);
                this.stopWaveformAnimation();
            }
        };

        this.recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            const currentText = (finalTranscript || interimTranscript).trim().toLowerCase();
            this.updateStatus(currentText ? `"${currentText}"` : 'Слушаю...', true);

            if (finalTranscript.trim()) {
                const text = finalTranscript.trim();
                console.log('[Voice Engine] Final recognized speech:', text);
                
                // Wake word check if enabled
                if (this.wakeWordMode) {
                    const wakeWords = ['эй финансы', 'финансы', 'эй сэми', 'сэми', 'помощник'];
                    const matched = wakeWords.some(w => text.toLowerCase().includes(w));
                    if (matched) {
                        const cleanCommand = text.toLowerCase()
                            .replace(/эй финансы|финансы|эй сэми|сэми|помощник/gi, '').trim();
                        if (cleanCommand && this.onCommandCallback) {
                            this.onCommandCallback(cleanCommand);
                        }
                    }
                } else {
                    if (this.onCommandCallback) {
                        this.onCommandCallback(text);
                    }
                }
            }
        };

        this.recognition.onerror = (event) => {
            console.error('[Voice Engine] Error:', event.error);
            if (event.error !== 'no-speech') {
                let errMsg = `Ошибка: ${event.error}`;
                if (event.error === 'not-allowed') {
                    errMsg = '⚠️ Ошибка: нет доступа к микрофону. Откройте ссылку в Safari/Chrome!';
                } else if (event.error === 'network') {
                    errMsg = '⚠️ Ошибка сети при распознавании.';
                }
                this.updateStatus(errMsg, false);
            }
        };

        return true;
    }

    startListening() {
        if (!this.recognition) {
            const ok = this.initRecognition();
            if (!ok) {
                const errMsg = '⚠️ Голосовой ввод не поддерживается в Telegram. Откройте ссылку в Safari/Chrome!';
                this.updateStatus(errMsg, false);
                alert(errMsg);
                return;
            }
        }
        try {
            this.recognition.start();
        } catch (e) {
            console.log('[Voice Engine] Already listening');
        }
    }

    stopListening() {
        if (this.recognition && this.isListening) {
            this.wakeWordMode = false;
            this.recognition.stop();
        }
    }

    toggleListening() {
        if (this.isListening) {
            this.stopListening();
        } else {
            this.startListening();
        }
    }

    speak(text, onEndCallback = null) {
        if (!this.synth) return;
        
        // Cancel ongoing speech
        this.synth.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = this.lang;
        utterance.rate = 1.0;
        utterance.pitch = 1.0;

        // Try to select Russian voice
        const voices = this.synth.getVoices();
        const ruVoice = voices.find(v => v.lang.includes('ru') || v.lang.includes('RU'));
        if (ruVoice) {
            utterance.voice = ruVoice;
        }

        if (onEndCallback) {
            utterance.onend = onEndCallback;
        }

        this.synth.speak(utterance);
    }

    updateStatus(text, listening = false) {
        if (this.onStatusChange) {
            this.onStatusChange(text, listening);
        }
    }

    startWaveformAnimation() {
        if (!this.canvasCtx) return;
        let step = 0;
        
        const draw = () => {
            const ctx = this.canvasCtx;
            const width = this.canvas.width;
            const height = this.canvas.height;
            
            ctx.clearRect(0, 0, width, height);
            
            ctx.lineWidth = 2;
            ctx.strokeStyle = '#6366F1';
            ctx.beginPath();
            
            const amplitude = 12;
            const frequency = 0.05;
            
            for (let x = 0; x < width; x++) {
                const y = height / 2 + Math.sin(x * frequency + step) * amplitude * Math.sin(x / width * Math.PI);
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            
            // Secondary glowing line
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = '#8B5CF6';
            ctx.beginPath();
            for (let x = 0; x < width; x++) {
                const y = height / 2 + Math.cos(x * frequency * 1.3 - step) * (amplitude * 0.7) * Math.sin(x / width * Math.PI);
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();

            step += 0.1;
            this.animFrameId = requestAnimationFrame(draw);
        };
        draw();
    }

    stopWaveformAnimation() {
        if (this.animFrameId) {
            cancelAnimationFrame(this.animFrameId);
            this.animFrameId = null;
        }
        if (this.canvasCtx) {
            this.canvasCtx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
    }
}
