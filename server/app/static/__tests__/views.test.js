const { ViewManager, BaseView } = require('../views');

describe('ViewManager', () => {
    let viewManager;

    beforeEach(() => {
        document.body.innerHTML = `
            <div id="main"></div>
            <div class="nav-item" data-view="test"></div>
            <div class="nav-item" data-view="second"></div>
        `;
        viewManager = new ViewManager();
        global.window.applyProvisioningAvailability = jest.fn();
        global.window.agentDeploymentState = { state: 'ready' };
        viewManager.init('main');
    });

    afterEach(() => {
        delete global.window.applyProvisioningAvailability;
        delete global.window.agentDeploymentState;
    });

    it('renders registered views and updates navigation state', async () => {
        let cleanupCalled = false;

        class TestView extends BaseView {
            async render() {
                return '<span class="content">Hello</span>';
            }

            init() {
                this.initialized = true;
            }

            cleanup() {
                cleanupCalled = true;
            }
        }

        class SecondView extends BaseView {
            async render() {
                return '<span>Second</span>';
            }
        }

        viewManager.registerView('test', TestView);
        viewManager.registerView('second', SecondView);

        await viewManager.switchView('test', { foo: 'bar' });

        const container = document.getElementById('main');
        expect(container.innerHTML).toContain('Hello');
        expect(viewManager.currentView).toBeInstanceOf(TestView);
        expect(viewManager.currentView.data).toEqual({ foo: 'bar' });
        expect(window.applyProvisioningAvailability).toHaveBeenCalledWith(
            window.agentDeploymentState,
        );

        const navItem = document.querySelector('[data-view="test"]');
        expect(navItem.classList.contains('active')).toBe(true);

        await viewManager.switchView('second');
        expect(cleanupCalled).toBe(true);
        const secondNav = document.querySelector('[data-view="second"]');
        expect(secondNav.classList.contains('active')).toBe(true);
    });

    it('logs an error when the container element cannot be found', () => {
        document.body.innerHTML = '';
        viewManager = new ViewManager();
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

        viewManager.init('missing-container');

        expect(errorSpy).toHaveBeenCalled();
        expect(viewManager.viewContainer).toBeNull();

        errorSpy.mockRestore();
    });
});
