"""Playwright 안티디텍트 스텔스 스크립트 — 공유 모듈"""

STEALTH_INIT_SCRIPT = """
// navigator.webdriver 제거
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Chrome runtime 위장
window.chrome = {
    runtime: {},
    loadTimes: function(){},
    csi: function(){},
    app: {isInstalled: false, InstallState: {DISABLED:'disabled',INSTALLED:'installed',NOT_INSTALLED:'not_installed'}, RunningState: {CANNOT_RUN:'cannot_run',READY_TO_RUN:'ready_to_run',RUNNING:'running'}},
};

// Permissions API 위장
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
);

// plugins 위장 (빈 배열이면 탐지됨)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
        {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
        {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''},
    ],
});

// languages 위장
Object.defineProperty(navigator, 'languages', {
    get: () => ['ko-KR', 'ko', 'en-US', 'en'],
});

// WebGL vendor/renderer 위장
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};

// connection.rtt 위장 (자동화 봇은 0인 경우가 많음)
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'rtt', {get: () => 50});
}

// Notification 위장
if (!window.Notification) {
    window.Notification = {permission: 'default'};
}
"""
