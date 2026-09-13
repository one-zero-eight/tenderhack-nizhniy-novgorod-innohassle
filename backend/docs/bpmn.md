# Support chat BPMN diagram

Recreation of [bpmn.jpg](bpmn.jpg), with the Russian captions, six swimlanes,
activities, gateways, events, documents, stores, colors, and connection routes.
Coordinates are enlarged uniformly by 1.5 for readable, editable vector output.

- [bpmn.bpmn](bpmn.bpmn): BPMN 2.0 XML, including diagram interchange (DI)
  positions, label bounds, colors, and waypoints. This is the diagram source.
- [bpmn.html](bpmn.html): a browser editor with zoom, editing, and BPMN/SVG downloads.
- [bpmn.js](bpmn.js): bpmn-js initialization, XML loading, export controls, and
  a renderer for the horizontal lane headings used in the JPG.

## Open the editor

From the backend directory:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory docs
```

Open <http://localhost:8080/bpmn.html>. The example loads **bpmn-js 18.28.0** from
unpkg and Open Sans from Google Fonts, so it needs an internet connection.
Double-click a caption to edit it, or drag diagram elements. Use **Скачать BPMN**
to save edits; changes are not written to the repository automatically.
**Скачать SVG** exports the current vector drawing, including horizontal lane captions.

## Import into an existing bpmn-js application

bpmn-js imports BPMN XML through `importXML`; see the
[official walkthrough](https://bpmn.io/toolkit/bpmn-js/walkthrough/).
Serve `bpmn.bpmn` with your application's static assets, then:

```js
import BpmnModeler from 'bpmn-js/lib/Modeler';
import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn.css';

const modeler = new BpmnModeler({ container: '#canvas' });
const response = await fetch('/bpmn.bpmn');
if (!response.ok) throw new Error(`Diagram request failed: ${response.status}`);
await modeler.importXML(await response.text());
modeler.get('canvas').zoom('fit-viewport');
```

Give `#canvas` an explicit height. The XML also opens directly in other BPMN
modelers. Standard renderers use their own fonts and vertical lane captions;
the custom horizontal captions and font settings are in `bpmn.js`.

## Interpretation of the source image

This is a visual transcription, with `isExecutable="false"`. The JPG contains
incomplete or unconventional control flow, which has been retained:

- The connection from **Ответ ИИ устраивает?** to **Есть ещё вопрос?** is labeled
  **Нет**. The handoff task also points upward to the first of these gateways.
- Escalation to line 2 points toward its decision gateway; escalation to line 3
  points directly to its resolution task. The separate **Принять обращение**
  tasks in those lanes have no incoming flows in the image.
- The administrator's problem gateway has only a **Нет** branch, followed by
  **Конец** and then an arrow toward problem analysis. No missing **Да** branch
  has been invented.
- Store connections and the arrow from **Конец** to analysis are BPMN
  associations. Consequently, some solid arrows in the JPG become dotted
  associations in the standard renderer; an end event has no outgoing sequence
  flow. The two journal symbols reference the same logical data store.
- **Периодический контроль** is represented by a timer start event, without
  inventing a schedule. A few connectors stop before a label, as in the JPG.

Browser verification covers warning-free import and XML round-trip, all six
lanes, caption editing, zoom, and BPMN/SVG downloads. This checks editor
compatibility; it does not turn the source drawing into an executable workflow.
