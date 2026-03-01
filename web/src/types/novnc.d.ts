// Type declarations for @novnc/novnc
declare module '@novnc/novnc/lib/rfb' {
    export * from '@novnc/novnc/core/rfb.js';
    export { default } from '@novnc/novnc/core/rfb.js';
}

declare module '@novnc/novnc/core/rfb.js' {
    interface RFBOptions {
        shared?: boolean;
        credentials?: {
            username?: string;
            password?: string;
            target?: string;
        };
        repeaterID?: string;
        wsProtocols?: string[];
    }

    interface RFBEventDetail {
        clean?: boolean;
        reason?: string;
    }

    interface RFBEvent extends Event {
        detail: RFBEventDetail;
    }

    export default class RFB {
        constructor(target: HTMLElement, url: string, options?: RFBOptions);

        // Properties
        viewOnly: boolean;
        scaleViewport: boolean;
        resizeSession: boolean;
        showDotCursor: boolean;
        clipViewport: boolean;
        dragViewport: boolean;
        focusOnClick: boolean;
        background: string;
        qualityLevel: number;
        compressionLevel: number;
        capabilities: {
            power: boolean;
        };

        // Methods
        disconnect(): void;
        sendCredentials(credentials: { username?: string; password?: string; target?: string }): void;
        sendKey(keysym: number, code: string, down?: boolean): void;
        sendCtrlAltDel(): void;
        focus(): void;
        blur(): void;
        machineShutdown(): void;
        machineReboot(): void;
        machineReset(): void;
        clipboardPasteFrom(text: string): void;

        // Event handling
        addEventListener(event: 'connect' | 'disconnect' | 'credentialsrequired' | 'securityfailure' | 'clipboard' | 'bell' | 'desktopname' | 'capabilities', handler: (e: RFBEvent) => void): void;
        removeEventListener(event: string, handler: (e: RFBEvent) => void): void;
    }
}
