/* global BpmnJS */

// The XML contains every BPMN element, color, label and waypoint. This small
// renderer only reproduces the horizontal lane captions from bpmn.jpg.
function HorizontalLaneLabels(eventBus, bpmnRenderer, textRenderer) {
  const svgNS = 'http://www.w3.org/2000/svg';

  eventBus.on('render.shape', 1500, (event) => {
    const { element, gfx, attrs } = event;
    if (element.type !== 'bpmn:Lane') return;

    const outline = bpmnRenderer.drawShape(gfx, element, attrs);
    gfx.querySelectorAll('text').forEach((label) => label.remove());

    const width = Math.min(129, element.width);
    const band = document.createElementNS(svgNS, 'rect');
    for (const [key, value] of Object.entries({
      width, height: element.height, fill: '#edf2f7', stroke: '#7f8792', 'stroke-width': 1,
    })) {
      band.setAttribute(key, value);
    }
    gfx.appendChild(band);
    gfx.appendChild(textRenderer.createText(element.businessObject.name || '', {
      box: { width, height: element.height },
      align: 'center-middle', padding: 4,
      style: { fontSize: 14, fontWeight: 700, fill: '#1a1a1a' },
    }));
    return outline;
  });
}

HorizontalLaneLabels.$inject = ['eventBus', 'bpmnRenderer', 'textRenderer'];

const status = document.querySelector('#status');

function showError(error) {
  console.error(error);
  status.dataset.error = 'true';
  status.textContent = `Не удалось открыть или сохранить схему: ${error.message}`;
}

function download(filename, contents, type) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function openDiagram() {
  if (typeof BpmnJS === 'undefined') {
    throw new Error('bpmn-js не загрузился. Проверьте доступ к unpkg.com.');
  }
  if (location.protocol === 'file:') {
    throw new Error('Откройте страницу через HTTP: python3 -m http.server 8080 --directory docs');
  }

  const response = await fetch('./bpmn.bpmn');
  if (!response.ok) throw new Error(`bpmn.bpmn: HTTP ${response.status}`);
  const xml = await response.text();

  const modeler = new BpmnJS({
    container: '#canvas',
    additionalModules: [{
      __init__: ['horizontalLaneLabels'],
      horizontalLaneLabels: ['type', HorizontalLaneLabels],
    }],
    textRenderer: {
      defaultStyle: { fontFamily: 'Arial, sans-serif', fontSize: 14, lineHeight: 1.15 },
      externalStyle: { fontSize: 13, lineHeight: 1.1 },
    },
    bpmnRenderer: { defaultStrokeColor: '#292d31', defaultLabelColor: '#1a1a1a' },
  });

  const { warnings } = await modeler.importXML(xml);
  const canvas = modeler.get('canvas');
  const fit = () => {
    // Leave space for the modeling palette on the left.
    const outer = canvas.getSize();
    const pool = modeler.get('elementRegistry').get('Participant_Support');
    const zoom = Math.min((outer.width - 100) / pool.width, (outer.height - 40) / pool.height);
    canvas.viewbox({
      x: pool.x - 85 / zoom, y: pool.y - 20 / zoom,
      width: outer.width / zoom, height: outer.height / zoom,
    });
  };
  fit();
  document.querySelectorAll('button').forEach((button) => { button.disabled = false; });
  document.querySelector('#fit').addEventListener('click', fit);
  document.querySelector('#zoom-in').addEventListener('click', () => canvas.zoom(canvas.zoom() * 1.2));
  document.querySelector('#zoom-out').addEventListener('click', () => canvas.zoom(canvas.zoom() / 1.2));
  document.querySelector('#save').addEventListener('click', async () => {
    try {
      const { xml: editedXML } = await modeler.saveXML({ format: true });
      download('support.bpmn', editedXML, 'application/xml;charset=utf-8');
    } catch (error) { showError(error); }
  });
  document.querySelector('#svg').addEventListener('click', async () => {
    try {
      const { svg } = await modeler.saveSVG();
      download('support.svg', svg, 'image/svg+xml;charset=utf-8');
    } catch (error) { showError(error); }
  });
  window.addEventListener('resize', fit);

  status.textContent = warnings.length
    ? `Схема открыта с предупреждениями: ${warnings.length}. Подробности в консоли.`
    : 'Схема готова. Двойной щелчок — изменить подпись; элементы можно перетаскивать. Скачайте BPMN, чтобы сохранить изменения.';
  if (warnings.length) console.warn('BPMN import warnings:', warnings);

  // Available for embedding experiments and inspecting the imported model.
  window.bpmnModeler = modeler;
}

openDiagram().catch(showError);
