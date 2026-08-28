import { Routes } from '@angular/router';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    title: 'DONNA — Your company, understood.',
    loadComponent: () => import('./features/landing/landing-page').then((m) => m.LandingPage),
  },
  {
    path: 'login',
    title: 'Sign in — DONNA',
    loadComponent: () => import('./features/auth/login-page').then((m) => m.LoginPage),
  },
  {
    path: 'signup',
    title: 'Create your account — DONNA',
    loadComponent: () => import('./features/auth/signup-page').then((m) => m.SignupPage),
  },
  {
    path: 'workspace',
    canActivate: [authGuard],
    loadComponent: () => import('./features/workspace/workspace-page').then((m) => m.WorkspacePage),
    children: [
      {
        path: '',
        title: 'Workspace — DONNA',
        loadComponent: () =>
          import('./features/workspace/workspace-home').then((m) => m.WorkspaceHome),
      },
      {
        path: 'settings',
        title: 'Settings — DONNA',
        loadComponent: () =>
          import('./features/workspace/settings-page').then((m) => m.SettingsPage),
      },
      {
        path: 'profile',
        title: 'Profile — DONNA',
        loadComponent: () => import('./features/workspace/profile-page').then((m) => m.ProfilePage),
      },
    ],
  },
  {
    path: 'forgot-password',
    title: 'Reset your password — DONNA',
    loadComponent: () => import('./features/auth/reset-page').then((m) => m.ResetPage),
  },
  {
    // Atterrissage du redirect OAuth backend (WEB_APP_URL + '/auth', voir
    // backend/app/xauth/src/routes/oauth.py) — jamais navigué à la main.
    path: 'auth',
    loadComponent: () =>
      import('./features/auth/oauth-callback-page').then((m) => m.OauthCallbackPage),
  },
  {
    path: 'terms',
    title: 'Terms of Service — DONNA',
    data: { doc: 'terms' },
    loadComponent: () => import('./features/legal/legal-page').then((m) => m.LegalPage),
  },
  {
    path: 'privacy',
    title: 'Privacy Policy — DONNA',
    data: { doc: 'privacy' },
    loadComponent: () => import('./features/legal/legal-page').then((m) => m.LegalPage),
  },
  { path: '**', redirectTo: '' },
];
