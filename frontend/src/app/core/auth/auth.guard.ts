import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { TokenStorage } from './token-storage';

/** Bloque /workspace sans session — jusqu'ici la route était grande ouverte. */
export const authGuard: CanActivateFn = () => {
  const tokens = inject(TokenStorage);
  if (tokens.hasSession()) return true;

  const router = inject(Router);
  return router.createUrlTree(['/login']);
};
