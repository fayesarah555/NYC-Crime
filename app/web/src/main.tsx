import {Component, StrictMode} from 'react';
import type {ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import '@astryxdesign/core/reset.css';
import '@astryxdesign/core/astryx.css';
import {Theme} from '@astryxdesign/core/theme';
import {InternationalizationProvider} from '@astryxdesign/core/i18n';
import {themes, defaultThemeSlug} from './astryx-themes';
import Dashboard from './pages/Dashboard';

// Second line of defence behind Dashboard's dataError guard: an unexpected
// render crash still shows a French message instead of a blank page.
class ErrorBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false};

  static getDerivedStateFromError() {
    return {failed: true};
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" style={{padding: '2rem', fontFamily: 'system-ui, sans-serif'}}>
        <h2>Chargement des données impossible</h2>
        <p>
          Une erreur inattendue a interrompu l'affichage. Rechargez la page ;
          si le problème persiste, l'export JSON est invalide.
        </p>
      </div>
    );
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Theme theme={themes[defaultThemeSlug]}>
      <ErrorBoundary>
        {/* The fr-FR catalog lacks the slider keys; name both thumbs in French. */}
        <InternationalizationProvider
          locale="fr-FR"
          overrides={{
            'fr-FR': {
              '@astryx.slider.minimumThumb': 'Début de la période',
              '@astryx.slider.maximumThumb': 'Fin de la période',
            },
          }}>
          <Dashboard />
        </InternationalizationProvider>
      </ErrorBoundary>
    </Theme>
  </StrictMode>,
);
