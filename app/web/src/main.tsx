import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import '@astryxdesign/core/reset.css';
import '@astryxdesign/core/astryx.css';
import {Theme} from '@astryxdesign/core/theme';
import {InternationalizationProvider} from '@astryxdesign/core/i18n';
import {themes, defaultThemeSlug} from './astryx-themes';
import Dashboard from './pages/Dashboard';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Theme theme={themes[defaultThemeSlug]}>
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
    </Theme>
  </StrictMode>,
);
