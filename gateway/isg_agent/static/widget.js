/**
 * DingDawg Agent 1 — Embeddable Chat Widget
 *
 * Usage:
 *   <script src="https://your-domain.com/api/v1/widget/embed.js"
 *           data-agent="@handle"
 *           data-position="bottom-right"
 *           data-color="#7C3AED">
 *   </script>
 *
 * Self-contained. Zero dependencies. Works cross-origin.
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------------
    // Configuration from script tag
    // -----------------------------------------------------------------------
    var script = document.currentScript;
    if (!script) {
        // Fallback for deferred / async: find the last script with data-agent
        var scripts = document.querySelectorAll('script[data-agent]');
        script = scripts[scripts.length - 1];
    }
    if (!script) return;

    var agentHandle = (script.getAttribute('data-agent') || '').replace(/^@/, '');
    var position = script.getAttribute('data-position') || 'bottom-right';
    var primaryColor = script.getAttribute('data-color') || '#7C3AED';

    if (!agentHandle) {
        console.error('[DingDawg Widget] data-agent attribute is required.');
        return;
    }

    // Derive the API base URL from the script src
    var srcUrl = script.src || '';
    var apiBase = srcUrl.replace(/\/api\/v1\/widget\/embed\.js.*$/, '')
                        .replace(/\/static\/widget\.js.*$/, '');
    // Strip trailing slash
    if (apiBase.endsWith('/')) apiBase = apiBase.slice(0, -1);

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    var STORAGE_SESSION_KEY = 'dd_widget_' + agentHandle + '_session';
    var STORAGE_VISITOR_KEY = 'dd_widget_visitor';
    var STORAGE_VOICE_KEY = 'dd_widget_' + agentHandle + '_voice';

    var sessionId = null;
    var visitorId = null;
    var isOpen = false;
    var agentConfig = null;
    var isSending = false;

    // Streaming state
    var supportsStreaming = (typeof ReadableStream !== 'undefined') &&
                            (typeof fetch !== 'undefined') &&
                            (typeof AbortController !== 'undefined');
    var currentStreamController = null;   // AbortController for the in-flight stream
    var userHasScrolledUp = false;        // auto-scroll guard

    // TTS state — default off, user must opt in
    var ttsSupported = !!(window.speechSynthesis);
    var voiceEnabled = false;
    try {
        voiceEnabled = (localStorage.getItem(STORAGE_VOICE_KEY) === 'on');
    } catch (e) { /* storage unavailable */ }

    // Safely read localStorage
    try {
        sessionId = localStorage.getItem(STORAGE_SESSION_KEY) || null;
        visitorId = localStorage.getItem(STORAGE_VISITOR_KEY) ||
                    ('visitor-' + Math.random().toString(36).substr(2, 8));
        localStorage.setItem(STORAGE_VISITOR_KEY, visitorId);
    } catch (e) {
        visitorId = 'visitor-' + Math.random().toString(36).substr(2, 8);
    }

    // -----------------------------------------------------------------------
    // CSS positioning helpers
    // -----------------------------------------------------------------------
    var posRight = position.indexOf('right') !== -1;
    var posTop = position.indexOf('top') !== -1;
    var hSide = posRight ? 'right: 20px; left: auto;' : 'left: 20px; right: auto;';
    var vBubble = posTop ? 'top: 20px; bottom: auto;' : 'bottom: 20px; top: auto;';
    var vContainer = posTop ? 'top: 90px; bottom: auto;' : 'bottom: 90px; top: auto;';

    // -----------------------------------------------------------------------
    // Inject styles
    // -----------------------------------------------------------------------
    var styleEl = document.createElement('style');
    styleEl.textContent = [
        '.dd-widget-bubble {',
        '  position: fixed;', hSide, vBubble,
        '  width: 60px; height: 60px; border-radius: 50%;',
        '  background: ' + primaryColor + '; color: #fff;',
        '  border: none; cursor: pointer;',
        '  box-shadow: 0 4px 12px rgba(0,0,0,0.15);',
        '  display: flex; align-items: center; justify-content: center;',
        '  font-size: 24px; z-index: 99999; transition: transform 0.2s;',
        '}',
        '.dd-widget-bubble:hover { transform: scale(1.1); }',
        '.dd-widget-bubble svg { width: 28px; height: 28px; fill: #fff; }',

        '.dd-widget-container {',
        '  position: fixed;', hSide, vContainer,
        '  width: 380px; max-width: calc(100vw - 40px);',
        '  height: 520px; max-height: calc(100vh - 120px);',
        '  background: #fff; border-radius: 16px;',
        '  box-shadow: 0 8px 32px rgba(0,0,0,0.12);',
        '  display: none; flex-direction: column; overflow: hidden;',
        '  z-index: 99999;',
        '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;',
        '}',
        '.dd-widget-container.open { display: flex; }',

        '.dd-widget-header {',
        '  padding: 16px; background: ' + primaryColor + '; color: #fff;',
        '  display: flex; align-items: center; gap: 12px; flex-shrink: 0;',
        '}',
        '.dd-widget-avatar {',
        '  width: 36px; height: 36px; border-radius: 50%;',
        '  background: rgba(255,255,255,0.2); display: flex;',
        '  align-items: center; justify-content: center; font-size: 16px;',
        '  flex-shrink: 0;',
        '}',
        '.dd-widget-header-info { flex: 1; min-width: 0; }',
        '.dd-widget-header-name { font-weight: 600; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
        '.dd-widget-header-status { font-size: 12px; opacity: 0.8; }',
        '.dd-widget-close {',
        '  margin-left: auto; background: none; border: none;',
        '  color: #fff; font-size: 22px; cursor: pointer; padding: 4px;',
        '  line-height: 1; flex-shrink: 0;',
        '}',

        '.dd-widget-messages {',
        '  flex: 1; overflow-y: auto; padding: 16px;',
        '  display: flex; flex-direction: column; gap: 12px;',
        '}',

        '.dd-widget-msg {',
        '  max-width: 80%; padding: 10px 14px; border-radius: 12px;',
        '  font-size: 14px; line-height: 1.4; word-wrap: break-word;',
        '}',
        '.dd-widget-msg.agent {',
        '  align-self: flex-start; background: #f0f0f0; color: #333;',
        '  border-bottom-left-radius: 4px;',
        '}',
        '.dd-widget-msg.user {',
        '  align-self: flex-end; background: ' + primaryColor + '; color: #fff;',
        '  border-bottom-right-radius: 4px;',
        '}',
        '.dd-widget-msg.typing {',
        '  align-self: flex-start; background: #f0f0f0; color: #999;',
        '  font-style: italic;',
        '}',

        '.dd-widget-input-area {',
        '  padding: 12px 16px; border-top: 1px solid #eee;',
        '  display: flex; gap: 8px; flex-shrink: 0;',
        '}',
        '.dd-widget-input {',
        '  flex: 1; border: 1px solid #ddd; border-radius: 24px;',
        '  padding: 10px 16px; font-size: 14px; outline: none;',
        '  font-family: inherit;',
        '}',
        '.dd-widget-input:focus { border-color: ' + primaryColor + '; }',
        '.dd-widget-send {',
        '  width: 40px; height: 40px; border-radius: 50%;',
        '  background: ' + primaryColor + '; color: #fff;',
        '  border: none; cursor: pointer; display: flex;',
        '  align-items: center; justify-content: center; font-size: 16px;',
        '  flex-shrink: 0; transition: opacity 0.2s;',
        '}',
        '.dd-widget-send:disabled { opacity: 0.5; cursor: not-allowed; }',
        '.dd-widget-send svg { width: 18px; height: 18px; fill: #fff; }',

        '.dd-widget-powered {',
        '  text-align: center; padding: 6px; font-size: 11px; color: #999;',
        '  flex-shrink: 0;',
        '}',
        '.dd-widget-powered a { color: #666; text-decoration: none; }',
        '.dd-widget-powered a:hover { text-decoration: underline; }',

        '.dd-widget-voice-toggle {',
        '  background: none; border: none; color: #fff;',
        '  font-size: 18px; cursor: pointer; padding: 4px;',
        '  line-height: 1; flex-shrink: 0; opacity: 0.7;',
        '  transition: opacity 0.2s;',
        '}',
        '.dd-widget-voice-toggle:hover { opacity: 1; }',
        '.dd-widget-voice-toggle.active { opacity: 1; }',

        '.dd-widget-msg.agent { position: relative; }',
        '.dd-widget-msg-speak {',
        '  display: none; position: absolute; right: -28px; top: 50%;',
        '  transform: translateY(-50%);',
        '  background: none; border: none; font-size: 14px;',
        '  cursor: pointer; padding: 4px; line-height: 1;',
        '  color: #999; transition: color 0.2s;',
        '}',
        '.dd-widget-msg-speak:hover { color: #555; }',
        '.dd-widget-msg.agent:hover .dd-widget-msg-speak { display: block; }',

        // Streaming cursor blink animation
        '@keyframes dd-cursor-blink {',
        '  0%, 100% { opacity: 1; }',
        '  50% { opacity: 0; }',
        '}',
        '.dd-widget-msg.streaming::after {',
        '  content: "\\25AE";',       // ▮ block cursor character
        '  display: inline-block;',
        '  margin-left: 2px;',
        '  animation: dd-cursor-blink 0.7s step-end infinite;',
        '  color: #666;',
        '  font-size: 12px;',
        '  vertical-align: middle;',
        '}',

        '@media (max-width: 480px) {',
        '  .dd-widget-container {',
        '    width: calc(100vw - 20px); height: calc(100vh - 100px);',
        '    right: 10px; left: 10px; bottom: 80px; top: auto;',
        '  }',
        '  .dd-widget-msg-speak { display: block; right: -24px; }',
        '}',
    ].join('\n');
    document.head.appendChild(styleEl);

    // -----------------------------------------------------------------------
    // Build DOM
    // -----------------------------------------------------------------------
    // Chat icon SVG (speech bubble)
    var chatIconSVG = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>';
    // Send arrow SVG
    var sendIconSVG = '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
    // Close icon
    var closeIconChar = '\u00D7';

    // Bubble
    var bubble = document.createElement('button');
    bubble.className = 'dd-widget-bubble';
    bubble.setAttribute('aria-label', 'Open chat');
    bubble.innerHTML = chatIconSVG;

    // Container
    var container = document.createElement('div');
    container.className = 'dd-widget-container';

    // Header
    var header = document.createElement('div');
    header.className = 'dd-widget-header';

    var avatar = document.createElement('div');
    avatar.className = 'dd-widget-avatar';
    avatar.textContent = '?';

    var headerInfo = document.createElement('div');
    headerInfo.className = 'dd-widget-header-info';

    var headerName = document.createElement('div');
    headerName.className = 'dd-widget-header-name';
    headerName.textContent = 'Agent';

    var headerStatus = document.createElement('div');
    headerStatus.className = 'dd-widget-header-status';
    headerStatus.textContent = 'Online';

    headerInfo.appendChild(headerName);
    headerInfo.appendChild(headerStatus);

    var voiceToggleBtn = document.createElement('button');
    voiceToggleBtn.className = 'dd-widget-voice-toggle' + (voiceEnabled ? ' active' : '');
    voiceToggleBtn.setAttribute('aria-label', 'Toggle voice');
    voiceToggleBtn.textContent = voiceEnabled ? '\uD83D\uDD0A' : '\uD83D\uDD07';
    // Hide entirely if TTS is not supported in this browser
    if (!ttsSupported) voiceToggleBtn.style.display = 'none';

    var closeBtn = document.createElement('button');
    closeBtn.className = 'dd-widget-close';
    closeBtn.setAttribute('aria-label', 'Close chat');
    closeBtn.textContent = closeIconChar;

    header.appendChild(avatar);
    header.appendChild(headerInfo);
    header.appendChild(voiceToggleBtn);
    header.appendChild(closeBtn);

    // Messages area
    var messagesArea = document.createElement('div');
    messagesArea.className = 'dd-widget-messages';

    // Input area
    var inputArea = document.createElement('div');
    inputArea.className = 'dd-widget-input-area';

    var input = document.createElement('input');
    input.className = 'dd-widget-input';
    input.setAttribute('type', 'text');
    input.setAttribute('placeholder', 'Type a message...');
    input.setAttribute('autocomplete', 'off');

    var sendBtn = document.createElement('button');
    sendBtn.className = 'dd-widget-send';
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.innerHTML = sendIconSVG;
    sendBtn.disabled = true;

    inputArea.appendChild(input);
    inputArea.appendChild(sendBtn);

    // Powered-by footer
    var powered = document.createElement('div');
    powered.className = 'dd-widget-powered';
    powered.innerHTML = 'Powered by <a href="https://dingdawg.com" target="_blank" rel="noopener">DingDawg</a>';

    // Assemble container
    container.appendChild(header);
    container.appendChild(messagesArea);
    container.appendChild(inputArea);
    container.appendChild(powered);

    // Append to body
    document.body.appendChild(bubble);
    document.body.appendChild(container);

    // -----------------------------------------------------------------------
    // API helpers
    // -----------------------------------------------------------------------
    function apiGet(path) {
        return fetch(apiBase + path, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function apiPost(path, body) {
        return fetch(apiBase + path, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify(body),
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    // -----------------------------------------------------------------------
    // Message rendering
    // -----------------------------------------------------------------------
    function addMessage(text, role) {
        var msg = document.createElement('div');
        msg.className = 'dd-widget-msg ' + role;
        msg.textContent = text;

        // Attach a per-message speak button on agent messages (only if TTS available)
        if (role === 'agent' && ttsSupported) {
            var speakBtn = document.createElement('button');
            speakBtn.className = 'dd-widget-msg-speak';
            speakBtn.setAttribute('aria-label', 'Speak this message');
            speakBtn.textContent = '\uD83D\uDD0A';
            speakBtn.setAttribute('data-msg-text', text);
            speakBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                speakText(speakBtn.getAttribute('data-msg-text') || '');
            });
            msg.appendChild(speakBtn);
        }

        messagesArea.appendChild(msg);
        _autoScroll();
        return msg;
    }

    function showTyping() {
        var msg = document.createElement('div');
        msg.className = 'dd-widget-msg typing';
        msg.setAttribute('data-typing', '1');
        msg.textContent = 'Typing...';
        messagesArea.appendChild(msg);
        _autoScroll();
        return msg;
    }

    function removeTyping() {
        var els = messagesArea.querySelectorAll('[data-typing]');
        for (var i = 0; i < els.length; i++) {
            els[i].parentNode.removeChild(els[i]);
        }
    }

    // -----------------------------------------------------------------------
    // Text-to-Speech
    // -----------------------------------------------------------------------
    function speakText(text) {
        if (!ttsSupported) return;
        window.speechSynthesis.cancel();
        var utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        // Prefer a natural-sounding voice if available
        var voices = window.speechSynthesis.getVoices();
        var preferred = voices.find(function (v) {
            return v.name.indexOf('Google') !== -1 ||
                   v.name.indexOf('Samantha') !== -1 ||
                   v.name.indexOf('Natural') !== -1;
        });
        if (preferred) utterance.voice = preferred;
        window.speechSynthesis.speak(utterance);
    }

    function setVoiceEnabled(val) {
        voiceEnabled = val;
        voiceToggleBtn.textContent = voiceEnabled ? '\uD83D\uDD0A' : '\uD83D\uDD07';
        if (voiceEnabled) {
            voiceToggleBtn.classList.add('active');
        } else {
            voiceToggleBtn.classList.remove('active');
            if (ttsSupported) window.speechSynthesis.cancel();
        }
        try {
            localStorage.setItem(STORAGE_VOICE_KEY, voiceEnabled ? 'on' : 'off');
        } catch (e) { /* storage unavailable */ }
    }

    // -----------------------------------------------------------------------
    // Core logic
    // -----------------------------------------------------------------------
    function loadConfig() {
        apiGet('/api/v1/widget/' + encodeURIComponent(agentHandle) + '/config')
            .then(function (cfg) {
                agentConfig = cfg;
                headerName.textContent = cfg.agent_name || 'Agent';
                if (cfg.avatar_url) {
                    avatar.textContent = '';
                    var img = document.createElement('img');
                    img.src = cfg.avatar_url;
                    img.style.cssText = 'width:100%;height:100%;border-radius:50%;object-fit:cover;';
                    avatar.appendChild(img);
                } else {
                    // Use first letter of agent name
                    var name = cfg.agent_name || 'A';
                    avatar.textContent = name.charAt(0).toUpperCase();
                }
            })
            .catch(function (err) {
                console.warn('[DingDawg Widget] Could not load agent config:', err);
            });
    }

    function ensureSession() {
        if (sessionId) return Promise.resolve(sessionId);

        return apiPost('/api/v1/widget/' + encodeURIComponent(agentHandle) + '/session', {
            visitor_id: visitorId,
        }).then(function (data) {
            sessionId = data.session_id;
            try {
                localStorage.setItem(STORAGE_SESSION_KEY, sessionId);
            } catch (e) { /* storage unavailable */ }

            // Display greeting if returned
            if (data.greeting_message) {
                addMessage(data.greeting_message, 'agent');
            }
            return sessionId;
        });
    }

    // -----------------------------------------------------------------------
    // Streaming message send (primary path)
    // -----------------------------------------------------------------------

    /**
     * Send a message using SSE streaming (fetch + ReadableStream).
     * Tokens appear in real-time as the LLM generates them.
     *
     * Falls back to sendMessageFallback() if:
     *  - Browser does not support ReadableStream / AbortController
     *  - The /stream endpoint returns a non-2xx status
     *
     * @param {string} text - The user's message text (already trimmed).
     * @param {string} sid  - Active session ID.
     */
    function sendMessageStreaming(text, sid) {
        // Cancel any previous in-flight stream
        if (currentStreamController) {
            currentStreamController.abort();
            currentStreamController = null;
        }

        var controller = new AbortController();
        currentStreamController = controller;

        var streamUrl = apiBase + '/api/v1/widget/' + encodeURIComponent(agentHandle) + '/stream';

        removeTyping();

        // Create the agent message bubble — tokens will be appended here
        var agentBubble = document.createElement('div');
        agentBubble.className = 'dd-widget-msg agent streaming';
        // Use a text node so tokens are appended safely without HTML re-parsing
        var textNode = document.createTextNode('');
        agentBubble.appendChild(textNode);
        messagesArea.appendChild(agentBubble);
        _autoScroll();

        var firstToken = true;
        var tokenBuffer = '';
        var rafPending = false;
        var decoder = new TextDecoder('utf-8');
        var sseBuffer = '';

        // Batch token flushes to stay at 60fps
        function flushTokenBuffer() {
            rafPending = false;
            if (tokenBuffer) {
                textNode.textContent += tokenBuffer;
                tokenBuffer = '';
                _autoScroll();
            }
        }

        function appendToken(token) {
            if (firstToken) {
                // Hide typing indicator on first token
                firstToken = false;
            }
            tokenBuffer += token;
            if (!rafPending) {
                rafPending = true;
                requestAnimationFrame(flushTokenBuffer);
            }
        }

        /**
         * Parse a line-by-line SSE buffer and dispatch parsed events.
         * @param {string} chunk - New text to append to the parse buffer.
         * @returns {Array} Array of parsed {event, data} objects.
         */
        function parseSseChunk(chunk) {
            sseBuffer += chunk;
            var events = [];
            var blocks = sseBuffer.split('\n\n');
            // Keep the last (potentially incomplete) block in the buffer
            sseBuffer = blocks.pop();

            for (var i = 0; i < blocks.length; i++) {
                var block = blocks[i].trim();
                if (!block) continue;
                var lines = block.split('\n');
                var evt = { event: 'message', data: null };
                for (var j = 0; j < lines.length; j++) {
                    var line = lines[j];
                    if (line.indexOf('event:') === 0) {
                        evt.event = line.slice(6).trim();
                    } else if (line.indexOf('data:') === 0) {
                        var rawData = line.slice(5).trim();
                        try {
                            evt.data = JSON.parse(rawData);
                        } catch (e) {
                            evt.data = rawData;
                        }
                    }
                }
                if (evt.data !== null) {
                    events.push(evt);
                }
            }
            return events;
        }

        function finaliseStreamBubble(fullResponse) {
            // Flush any remaining buffered tokens immediately
            if (tokenBuffer) {
                textNode.textContent += tokenBuffer;
                tokenBuffer = '';
            }
            // Remove streaming cursor class
            agentBubble.classList.remove('streaming');
            // Attach per-message speak button now that the text is final
            if (ttsSupported) {
                var speakBtn = document.createElement('button');
                speakBtn.className = 'dd-widget-msg-speak';
                speakBtn.setAttribute('aria-label', 'Speak this message');
                speakBtn.textContent = '\uD83D\uDD0A';
                speakBtn.setAttribute('data-msg-text', fullResponse);
                speakBtn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    speakText(speakBtn.getAttribute('data-msg-text') || '');
                });
                agentBubble.appendChild(speakBtn);
            }
            _autoScroll();
        }

        fetch(streamUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify({
                session_id: sid,
                message: text,
                visitor_id: visitorId,
            }),
            signal: controller.signal,
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            if (!response.body) {
                throw new Error('ReadableStream not available in response');
            }

            var reader = response.body.getReader();

            function pump() {
                return reader.read().then(function (result) {
                    if (result.done) {
                        return;
                    }
                    var chunk = decoder.decode(result.value, { stream: true });
                    var parsedEvents = parseSseChunk(chunk);

                    for (var i = 0; i < parsedEvents.length; i++) {
                        var ev = parsedEvents[i];
                        var d = ev.data;
                        if (!d || typeof d !== 'object') continue;

                        if (d.type === 'token' && d.token) {
                            appendToken(d.token);
                        } else if (d.type === 'done') {
                            finaliseStreamBubble(d.full_response || textNode.textContent);
                            if (voiceEnabled && d.full_response) {
                                speakText(d.full_response);
                            }
                            if (d.session_id && d.session_id !== sessionId) {
                                sessionId = d.session_id;
                                try {
                                    localStorage.setItem(STORAGE_SESSION_KEY, sessionId);
                                } catch (e) { /* storage unavailable */ }
                            }
                        } else if (d.type === 'error') {
                            // Flush partial content if any
                            if (tokenBuffer) {
                                textNode.textContent += tokenBuffer;
                                tokenBuffer = '';
                            }
                            agentBubble.classList.remove('streaming');
                            if (!textNode.textContent) {
                                // No tokens were received — replace with error message
                                textNode.textContent = d.message || 'Sorry, something went wrong. Please try again.';
                            } else {
                                // Show partial content + interrupted notice
                                textNode.textContent += ' [Response interrupted]';
                            }
                            _autoScroll();
                        }
                        // action events: no UI change needed (done event follows)
                    }

                    return pump();
                });
            }

            return pump();
        })
        .catch(function (err) {
            if (err && err.name === 'AbortError') {
                // User sent a new message — silently discard the old stream
                return;
            }
            console.warn('[DingDawg Widget] Streaming failed, falling back to /message:', err);
            // Remove the partially-filled streaming bubble
            if (agentBubble && agentBubble.parentNode) {
                agentBubble.parentNode.removeChild(agentBubble);
            }
            // Fallback to non-streaming endpoint
            sendMessageFallback(text, sid);
            return;
        })
        .then(function () {
            currentStreamController = null;
            isSending = false;
            updateSendButton();
        });
    }

    // -----------------------------------------------------------------------
    // Non-streaming fallback (original /message endpoint)
    // -----------------------------------------------------------------------

    function sendMessageFallback(text, sid) {
        var typingEl = showTyping();

        apiPost('/api/v1/widget/' + encodeURIComponent(agentHandle) + '/message', {
            session_id: sid,
            message: text,
            visitor_id: visitorId,
        })
        .then(function (data) {
            removeTyping();
            var responseText = data.response || data.text || '';
            addMessage(responseText, 'agent');

            if (voiceEnabled && responseText) {
                speakText(responseText);
            }

            if (data.session_id && data.session_id !== sessionId) {
                sessionId = data.session_id;
                try {
                    localStorage.setItem(STORAGE_SESSION_KEY, sessionId);
                } catch (e) { /* storage unavailable */ }
            }
        })
        .catch(function (err) {
            removeTyping();
            console.error('[DingDawg Widget] Message fallback failed:', err);

            if (err.message && err.message.indexOf('404') !== -1) {
                sessionId = null;
                try { localStorage.removeItem(STORAGE_SESSION_KEY); } catch (e) {}
                addMessage('Session expired. Please send your message again.', 'agent');
            } else {
                addMessage('Sorry, something went wrong. Please try again.', 'agent');
            }
        })
        .then(function () {
            isSending = false;
            updateSendButton();
        });
    }

    // -----------------------------------------------------------------------
    // Main sendMessage — routes to streaming or fallback
    // -----------------------------------------------------------------------

    function sendMessage() {
        var text = input.value.trim();
        if (!text || isSending) return;

        isSending = true;
        sendBtn.disabled = true;
        input.value = '';

        addMessage(text, 'user');

        ensureSession()
            .then(function (sid) {
                if (supportsStreaming) {
                    showTyping();
                    sendMessageStreaming(text, sid);
                } else {
                    sendMessageFallback(text, sid);
                }
            })
            .catch(function (err) {
                console.error('[DingDawg Widget] Session setup failed:', err);
                addMessage('Sorry, could not connect. Please try again.', 'agent');
                isSending = false;
                updateSendButton();
            });
    }

    // -----------------------------------------------------------------------
    // Auto-scroll helper
    // -----------------------------------------------------------------------

    function _autoScroll() {
        if (!userHasScrolledUp) {
            messagesArea.scrollTop = messagesArea.scrollHeight;
        }
    }

    function toggle() {
        isOpen = !isOpen;
        if (isOpen) {
            container.classList.add('open');
            bubble.innerHTML = closeIconChar;
            bubble.style.fontSize = '28px';
            input.focus();

            // Show greeting on first open if no messages exist
            if (messagesArea.children.length === 0) {
                var greeting = (agentConfig && agentConfig.greeting) ||
                               'Hello! How can I help you today?';
                addMessage(greeting, 'agent');
            }
        } else {
            container.classList.remove('open');
            bubble.innerHTML = chatIconSVG;
            bubble.style.fontSize = '24px';
        }
    }

    function updateSendButton() {
        sendBtn.disabled = isSending || !input.value.trim();
    }

    // -----------------------------------------------------------------------
    // Event listeners
    // -----------------------------------------------------------------------
    bubble.addEventListener('click', toggle);
    closeBtn.addEventListener('click', toggle);

    voiceToggleBtn.addEventListener('click', function () {
        setVoiceEnabled(!voiceEnabled);
    });

    sendBtn.addEventListener('click', sendMessage);

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    input.addEventListener('input', updateSendButton);

    // Track whether the user has manually scrolled up — if so, pause auto-scroll.
    // Resume auto-scroll when the user scrolls back to the bottom.
    messagesArea.addEventListener('scroll', function () {
        var distanceFromBottom = messagesArea.scrollHeight -
                                 messagesArea.scrollTop -
                                 messagesArea.clientHeight;
        // Consider "at bottom" if within 40px (accounts for sub-pixel rounding)
        userHasScrolledUp = distanceFromBottom > 40;
    });

    // -----------------------------------------------------------------------
    // Initialise
    // -----------------------------------------------------------------------
    loadConfig();
})();
