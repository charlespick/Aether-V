(function () {
    'use strict';

    function readConfig() {
        const configElement = document.getElementById('login-config');
        if (!configElement) {
            return { auth_enabled: true };
        }

        try {
            return JSON.parse(configElement.textContent || '{}');
        } catch (error) {
            console.error('Failed to parse login configuration payload:', error);
            return { auth_enabled: true };
        }
    }

    function setError(message) {
        const errorEl = document.getElementById('login-error');
        if (!errorEl) {
            return;
        }

        if (message) {
            errorEl.textContent = message;
            errorEl.hidden = false;
        } else {
            errorEl.textContent = '';
            errorEl.hidden = true;
        }
    }

    async function handleDirectLogin(button) {
        try {
            const response = await fetch('/auth/direct-login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                let detail = 'Unable to complete direct login. Please try again.';
                try {
                    const payload = await response.json();
                    detail = payload.detail || payload.message || detail;
                } catch (parseError) {
                    console.warn('Failed to parse error payload from direct login:', parseError);
                }
                throw new Error(detail);
            }

            window.location.href = '/';
        } catch (error) {
            console.error('Direct login failed:', error);
            setError(error.message || 'Unexpected error during login.');
            button.disabled = false;
            button.classList.remove('is-loading');
        }
    }

    function initialize() {
        const config = readConfig();
        const loginButton = document.getElementById('login-button');
        if (!loginButton) {
            return;
        }

        loginButton.addEventListener('click', function () {
            setError('');
            loginButton.disabled = true;
            loginButton.classList.add('is-loading');

            const authEnabledAttr = loginButton.dataset.authEnabled;
            const authEnabled = authEnabledAttr ? authEnabledAttr === 'true' : Boolean(config.auth_enabled);

            if (authEnabled) {
                window.location.href = '/auth/login';
                return;
            }

            handleDirectLogin(loginButton);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }
})();
