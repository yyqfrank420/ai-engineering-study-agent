import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '../src/index.css';
import { GraphCanvas } from '../src/components/GraphCanvas';
import {
  customerSupportDenseGraph,
  growthMarketingDenseGraph,
} from '../src/components/GraphCanvas/__fixtures__/denseArchitectures';


const fixture = new URLSearchParams(window.location.search).get('fixture');
const graphData = fixture === 'support' ? customerSupportDenseGraph : growthMarketingDenseGraph;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <main style={{ width: '100vw', height: '100vh', background: '#080d14', display: 'flex' }}>
      <GraphCanvas
        graphData={graphData}
        animateSequence={false}
        authSession={null}
        activeThreadId={null}
        onNodeClick={() => undefined}
        onTellMeMore={() => undefined}
        onExpandGraph={() => undefined}
        selectedNode={null}
        onClosePopup={() => undefined}
        sourceTexts={[]}
      />
    </main>
  </StrictMode>,
);
