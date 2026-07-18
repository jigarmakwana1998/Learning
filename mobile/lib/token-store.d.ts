/** Shared type contract for the platform-specific token-store implementations. */
export declare function getToken(): Promise<string | null>;
export declare function setToken(token: string): Promise<void>;
export declare function clearToken(): Promise<void>;
