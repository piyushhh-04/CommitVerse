export const API_BASE_PATH = "/api/v1";

export type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

export interface ApiValidationDetail {
  field: string;
  code: string;
  message: string;
}

interface ApiErrorOptions {
  status: number | null;
  code: string;
  requestId: string | null;
  details?: ApiValidationDetail[];
  cause?: unknown;
}

interface ApiRequestOptions<TBody = unknown> {
  method?: HttpMethod;
  body?: TBody;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

interface RequestExtras {
  headers?: HeadersInit;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseDetails(value: unknown): ApiValidationDetail[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const details = value.flatMap((item): ApiValidationDetail[] => {
    if (
      !isRecord(item) ||
      typeof item.field !== "string" ||
      typeof item.code !== "string" ||
      typeof item.message !== "string"
    ) {
      return [];
    }
    return [{ field: item.field, code: item.code, message: item.message }];
  });

  return details.length > 0 ? details : undefined;
}

function getRequestId(payload: unknown, response: Response): string | null {
  if (isRecord(payload) && typeof payload.request_id === "string") {
    return payload.request_id;
  }
  return response.headers.get("X-Request-ID");
}

function createResponseError(response: Response, payload: unknown): ApiError {
  const requestId = getRequestId(payload, response);
  if (
    isRecord(payload) &&
    isRecord(payload.error) &&
    typeof payload.error.code === "string" &&
    typeof payload.error.message === "string"
  ) {
    const details = parseDetails(payload.error.details);
    return new ApiError(payload.error.message, {
      status: response.status,
      code: payload.error.code,
      requestId,
      ...(details ? { details } : {}),
    });
  }

  const message = response.statusText || `Request failed with status ${response.status}.`;
  return new ApiError(message, {
    status: response.status,
    code: "http_error",
    requestId,
  });
}

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly requestId: string | null;
  readonly details?: ApiValidationDetail[];

  constructor(message: string, options: ApiErrorOptions) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
    if (options.details) this.details = options.details;
  }
}

export class ApiClient {
  private csrfToken: string | null = null;

  get hasCsrfToken(): boolean {
    return this.csrfToken !== null;
  }

  setCsrfToken(token: string | null): void {
    this.csrfToken = token;
  }

  get<TResponse>(path: string, options: RequestExtras = {}): Promise<TResponse | undefined> {
    return this.request<TResponse>(path, { ...options, method: "GET" });
  }

  post<TResponse, TBody = undefined>(
    path: string,
    body?: TBody,
    options: RequestExtras = {},
  ): Promise<TResponse | undefined> {
    return this.mutate<TResponse, TBody>("POST", path, body, options);
  }

  patch<TResponse, TBody = undefined>(
    path: string,
    body?: TBody,
    options: RequestExtras = {},
  ): Promise<TResponse | undefined> {
    return this.mutate<TResponse, TBody>("PATCH", path, body, options);
  }

  delete<TResponse = void>(
    path: string,
    options: RequestExtras = {},
  ): Promise<TResponse | undefined> {
    return this.request<TResponse>(path, { ...options, method: "DELETE" });
  }

  private mutate<TResponse, TBody>(
    method: "POST" | "PATCH",
    path: string,
    body: TBody | undefined,
    options: RequestExtras,
  ): Promise<TResponse | undefined> {
    const requestOptions: ApiRequestOptions<TBody> = { ...options, method };
    if (body !== undefined) requestOptions.body = body;
    return this.request<TResponse, TBody>(path, requestOptions);
  }

  private async request<TResponse, TBody = unknown>(
    path: string,
    options: ApiRequestOptions<TBody>,
  ): Promise<TResponse | undefined> {
    if (!path.startsWith("/") || path.startsWith("//")) {
      throw new TypeError("API paths must be same-origin absolute paths.");
    }

    const method = options.method ?? "GET";
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (method !== "GET" && this.csrfToken) {
      headers.set("X-CSRF-Token", this.csrfToken);
    }

    const requestInit: RequestInit = {
      method,
      headers,
      credentials: "same-origin",
    };
    if (options.signal) requestInit.signal = options.signal;
    if (options.body !== undefined) requestInit.body = JSON.stringify(options.body);

    let response: Response;
    try {
      response = await fetch(`${API_BASE_PATH}${path}`, requestInit);
    } catch (cause) {
      if (cause instanceof Error && cause.name === "AbortError") throw cause;
      throw new ApiError("The Hub API could not be reached.", {
        status: null,
        code: "network_error",
        requestId: null,
        cause,
      });
    }

    const responseCsrfToken = response.headers.get("X-CSRF-Token");
    if (!options.signal?.aborted && responseCsrfToken !== null) {
      this.setCsrfToken(responseCsrfToken || null);
    } else if (
      !options.signal?.aborted &&
      response.ok &&
      (path === "/me" || path === "/auth/login" || path === "/auth/register")
    ) {
      this.setCsrfToken(null);
    }

    let responseText: string;
    try {
      responseText = await response.text();
    } catch (cause) {
      throw new ApiError("The Hub API response could not be read.", {
        status: response.status,
        code: "response_read_error",
        requestId: response.headers.get("X-Request-ID"),
        cause,
      });
    }

    if (responseText.trim() === "") {
      if (!response.ok) throw createResponseError(response, undefined);
      return undefined;
    }

    let payload: unknown;
    try {
      payload = JSON.parse(responseText);
    } catch (cause) {
      if (!response.ok) throw createResponseError(response, undefined);
      throw new ApiError("The Hub API returned an invalid JSON response.", {
        status: response.status,
        code: "invalid_response",
        requestId: response.headers.get("X-Request-ID"),
        cause,
      });
    }

    if (!response.ok) throw createResponseError(response, payload);
    return payload as TResponse;
  }
}

export const apiClient = new ApiClient();
