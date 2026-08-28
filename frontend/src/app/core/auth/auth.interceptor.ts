import { inject } from '@angular/core';
import { HttpInterceptorFn } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { TokenStorage } from './token-storage';

/**
 * Attache le Bearer token à toute requête vers l'API DONNA — jamais vers un
 * hôte tiers (Google, etc.), pour ne pas fuiter le jeton hors de notre backend.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiUrl)) return next(req);

  const token = inject(TokenStorage).accessToken;
  if (!token) return next(req);

  return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
};
