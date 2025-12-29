/**
 * API Client Service
 * 
 * Centralized HTTP client for all API requests.
 * Handles:
 * - Session-based authentication (cookies managed by browser)
 * - Request/response interceptors
 * - Error handling and standardized responses
 * - Base URL and common headers
 * 
 * Uses native fetch API with type-safe wrappers.
 */

interface ApiResponse<T = unknown> {
    ok: boolean;
    status: number;
    statusText: string;
    data?: T;
    error?: string;
}

interface RequestOptions extends RequestInit {
    params?: Record<string, string | number | boolean>;
    timeout?: number;
}

class ApiClient {
    private readonly baseUrl: string;
    private readonly defaultTimeout = 30000; // 30 seconds

    constructor() {
        // API is mounted at /api by FastAPI
        // Use relative paths - let reverse proxy/ingress handle routing
        // In production and codespaces, everything goes through the same entry point
        this.baseUrl = '';
    }

    /**
     * Perform a GET request.
     */
    async get<T = unknown>(endpoint: string, options?: RequestOptions): Promise<ApiResponse<T>> {
        return this.request<T>(endpoint, { ...options, method: 'GET' });
    }

    /**
     * Perform a POST request.
     */
    async post<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions): Promise<ApiResponse<T>> {
        return this.request<T>(endpoint, {
            ...options,
            method: 'POST',
            body: body ? JSON.stringify(body) : undefined
        });
    }

    /**
     * Perform a PUT request.
     */
    async put<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions): Promise<ApiResponse<T>> {
        return this.request<T>(endpoint, {
            ...options,
            method: 'PUT',
            body: body ? JSON.stringify(body) : undefined
        });
    }

    /**
     * Perform a PATCH request.
     */
    async patch<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions): Promise<ApiResponse<T>> {
        return this.request<T>(endpoint, {
            ...options,
            method: 'PATCH',
            body: body ? JSON.stringify(body) : undefined
        });
    }

    /**
     * Perform a DELETE request.
     */
    async delete<T = unknown>(endpoint: string, options?: RequestOptions): Promise<ApiResponse<T>> {
        return this.request<T>(endpoint, { ...options, method: 'DELETE' });
    }

    /**
     * Core request method.
     */
    private async request<T>(endpoint: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
        const { params, timeout = this.defaultTimeout, ...fetchOptions } = options;

        try {
            // Build URL with query parameters
            const url = this.buildUrl(endpoint, params);

            // Set default headers
            const headers = new Headers(fetchOptions.headers);
            if (!headers.has('Content-Type') && fetchOptions.body) {
                headers.set('Content-Type', 'application/json');
            }
            headers.set('Accept', 'application/json');

            // Create abort controller for timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), timeout);

            try {
                // Perform fetch
                // Session cookies are automatically included with credentials: 'same-origin'
                const response = await fetch(url, {
                    ...fetchOptions,
                    headers,
                    credentials: 'same-origin', // Include session cookies
                    signal: controller.signal
                });

                clearTimeout(timeoutId);

                // Parse response
                return await this.parseResponse<T>(response);

            } finally {
                clearTimeout(timeoutId);
            }

        } catch (error) {
            console.error(`API Error: ${endpoint}`, error);

            if (error instanceof Error) {
                if (error.name === 'AbortError') {
                    return {
                        ok: false,
                        status: 0,
                        statusText: 'Request Timeout',
                        error: 'Request timed out'
                    };
                }

                return {
                    ok: false,
                    status: 0,
                    statusText: 'Network Error',
                    error: error.message
                };
            }

            return {
                ok: false,
                status: 0,
                statusText: 'Unknown Error',
                error: 'An unexpected error occurred'
            };
        }
    }

    /**
     * Build full URL with query parameters.
     */
    private buildUrl(endpoint: string, params?: Record<string, string | number | boolean>): string {
        // Ensure endpoint starts with /
        const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

        // For relative URLs (empty baseUrl), construct path directly
        if (!this.baseUrl) {
            if (!params || Object.keys(params).length === 0) {
                return path;
            }

            // Manually build query string for relative URLs
            const queryString = Object.entries(params)
                .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
                .join('&');

            return `${path}?${queryString}`;
        }

        // For absolute URLs, use URL constructor
        const url = new URL(path, this.baseUrl);

        // Add query parameters
        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                url.searchParams.append(key, String(value));
            });
        }

        return url.toString();
    }

    /**
     * Parse fetch response into standardized format.
     */
    private async parseResponse<T>(response: Response): Promise<ApiResponse<T>> {
        const contentType = response.headers.get('content-type');
        const isJson = contentType?.includes('application/json');

        try {
            if (response.ok) {
                // Success response
                if (response.status === 204 || !isJson) {
                    // No content or non-JSON response
                    return {
                        ok: true,
                        status: response.status,
                        statusText: response.statusText
                    };
                }

                const data = await response.json();
                return {
                    ok: true,
                    status: response.status,
                    statusText: response.statusText,
                    data: data as T
                };

            } else {
                // Error response
                let error = response.statusText;

                if (isJson) {
                    try {
                        const errorData = await response.json();
                        // FastAPI returns { "detail": "error message" } for errors
                        error = errorData.detail || errorData.message || error;
                    } catch {
                        // Failed to parse error JSON, use statusText
                    }
                }

                return {
                    ok: false,
                    status: response.status,
                    statusText: response.statusText,
                    error
                };
            }

        } catch (error) {
            console.error('Failed to parse response', error);
            return {
                ok: false,
                status: response.status,
                statusText: response.statusText,
                error: 'Failed to parse server response'
            };
        }
    }

    /**
     * Check if the current session is valid.
     * Returns true if authenticated, false otherwise.
     */
    async checkAuth(): Promise<boolean> {
        try {
            const response = await this.get('/api/build-info');
            return response.ok;
        } catch {
            return false;
        }
    }

    /**
     * Initiate OIDC login flow.
     */
    login() {
        window.location.href = '/auth/login';
    }

    /**
     * Logout current user.
     */
    async logout() {
        try {
            await this.post('/auth/logout');
        } finally {
            // Redirect to logout page regardless of API response
            window.location.href = '/auth/logged-out';
        }
    }
}

// Export singleton instance
export const apiClient = new ApiClient();

// Export types for use in other modules
export type { ApiResponse, RequestOptions };
