import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '../src/index.css';
import { GraphCanvas } from '../src/components/GraphCanvas';
import { D3Graph } from '../src/components/GraphCanvas/D3Graph';
import {
  customerSupportDenseGraph,
  growthMarketingDenseGraph,
} from '../src/components/GraphCanvas/__fixtures__/denseArchitectures';
import { modelServingPaidCandidate } from '../src/components/GraphCanvas/__fixtures__/modelServingPaidCandidate';


const fixture = new URLSearchParams(window.location.search).get('fixture');
const graphData = fixture === 'support' ? customerSupportDenseGraph : growthMarketingDenseGraph;
const graph = fixture === 'paid-model-serving'
  ? (
      <D3Graph
        graphData={modelServingPaidCandidate}
        currentStep={-1}
        activeNodeIds={new Set<string>()}
        onNodeClick={() => undefined}
      />
    )
  : (
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
    );

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <main style={{ width: '100vw', height: '100vh', background: '#080d14', display: 'flex' }}>
      {graph}
    </main>
  </StrictMode>,
);
