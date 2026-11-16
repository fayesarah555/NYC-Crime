import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import Legend from './Legend';

describe('Legend cluster palette', () => {
  it('renders k colours and k legend rows for a k = 5 fixture', () => {
    const {container} = render(<Legend clusterMode types={[]} k={5} />);
    expect(screen.getAllByText(/^Cluster \d$/)).toHaveLength(5);
    const swatches = [...container.querySelectorAll('div')].filter(
      el => el.style.background !== '' && el.style.border === '',
    );
    // 5 clusters + the neutral « Hors cluster » swatch
    expect(swatches).toHaveLength(6);
  });

  it('fails loudly above the palette length', () => {
    expect(() => render(<Legend clusterMode types={[]} k={7} />)).toThrow(
      /k = 7/,
    );
  });
});
