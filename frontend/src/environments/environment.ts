/**
 * Config d'environnement — dev par défaut (ng serve). Pas de fileReplacements
 * dans angular.json pour l'instant : à ajouter (avec environment.prod.ts) le
 * jour d'un vrai build de prod.
 */
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000',
  wsUrl: 'ws://localhost:8000',
};
