import { lazy } from 'react';
import { Navigate } from 'react-router-dom';
import { ClaimsDashboard } from './pages/ClaimsDashboard';

const OAuthCallback = lazy(() => import('./pages/OAuthCallback'));

export const appRoutes = [
  { path: '/oauth/callback', element: <OAuthCallback /> },
  { path: '/', element: <ClaimsDashboard /> },
  { path: '*', element: <Navigate to="/" replace /> },
];
