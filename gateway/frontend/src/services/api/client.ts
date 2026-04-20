/**
 * Axios HTTP client with auth interceptors.
 *
 * - Adds Authorization Bearer token to every request
 * - Handles 401 with token refresh queue
 * - Provides typed get/post/put/del helpers
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { reportApiError } from "@/services/errorReporter";

// Token storage — memory + localStorage for persistence across page loads
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (typeof window !== "undefined") {
    if (token) {
      localStorage.setItem("access_token", token);
      // Keep cookie in sync so Next.js middleware auth guard passes
      document.cookie = `access_token=${token}; path=/; max-age=86400; SameSite=Lax; Secure`;
    } else {
      localStorage.removeItem("access_token");
      localStorage.removeItem("auth_user");
      // Clear cookie on logout
      document.cookie = "access_token=; path=/; max-age=0; SameSite=Lax; Secure";
    }
  }
}

export function getAccessToken(): string | null {
  if (accessToken) return accessToken;
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("access_token");
    if (stored) {
      accessToken = stored;
      return stored;
    }
  }
  return null;
}

// Refresh queue to avoid concurrent refresh calls
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

function processQueue(error: unknown, token: string | null = null): void {
  for (const prom of failedQueue) {
    if (error) {
      prom.reject(error);
    } else if (token) {
      prom.resolve(token);
    }
  }
  failedQueue = [];
}

const apiClient: AxiosInstance = axios.create({
  baseURL: "",
  timeout: 30_000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: attach token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: handle 401 and capture 5xx errors for reporting
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const originalRequest = error.config as AxiosRequestConfig & {
      _retry?: boolean;
    };

    // Report 5xx server errors to the client error capture system.
    // Skips the error-reporting endpoint itself to prevent feedback loops.
    const responseStatus: number | undefined = error.response?.status;
    const requestUrl: string = originalRequest?.url ?? "";
    if (
      responseStatus !== undefined &&
      responseStatus >= 500 &&
      !requestUrl.includes("/admin/client-errors")
    ) {
      const errorMessage: string =
        error.response?.data?.detail ??
        error.response?.data?.message ??
        error.message ??
        `HTTP ${responseStatus}`;
      reportApiError(requestUrl, responseStatus, String(errorMessage));
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      // Don't try to refresh if auth endpoints failed — that's credentials, not token expiry
      const reqUrl = originalRequest.url || '';
      if (reqUrl.includes('/auth/login') || reqUrl.includes('/auth/register')) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${token}`;
          }
          return apiClient(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // Use relative path — frontend always proxies through Vercel rewrites.
        const currentToken = getAccessToken();
        const res = await axios.post(`/auth/refresh`, {}, {
          headers: currentToken ? { Authorization: `Bearer ${currentToken}` } : {},
          withCredentials: true,
        });
        const newToken = res.data?.access_token;
        if (newToken) {
          setAccessToken(newToken);
          processQueue(null, newToken);
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${newToken}`;
          }
          return apiClient(originalRequest);
        } else {
          // Refresh returned 200 but no token — drain queue and redirect
          const noTokenError = new Error("Refresh returned no access_token");
          processQueue(noTokenError, null);
          setAccessToken(null);
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
          return Promise.reject(noTokenError);
        }
      } catch (refreshError) {
        processQueue(refreshError, null);
        setAccessToken(null);
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// Type-safe helpers
export async function get<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const res = await apiClient.get<T>(url, config);
  return res.data;
}

export async function post<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const res = await apiClient.post<T>(url, data, config);
  return res.data;
}

export async function put<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const res = await apiClient.put<T>(url, data, config);
  return res.data;
}

export async function del<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const res = await apiClient.delete<T>(url, config);
  return res.data;
}

export default apiClient;
