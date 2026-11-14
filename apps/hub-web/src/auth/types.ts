export interface AuthUser {
  id: string;
  email: string;
  username: string;
  display_name: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegistrationDetails extends LoginCredentials {
  username: string;
  display_name?: string;
}

export interface AuthStatusResponse {
  status: "ok";
}
