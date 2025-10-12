Kitchen UI (Vite + React)
=========================

This repository includes a lightweight Vite + React UI under `src/kitchen-ui`.

Purpose
-------
- Provide a simple, adjustable canvas-based topology visualization for the node
  manager.
- Ship the UI distribution as static files and serve them from the node-manager
  Docker image at runtime (we copy `dist/kitchen-ui` into the image).

How to run locally
------------------
1. Install Node.js (v18+ recommended).
2. From the repo root:

   npm install
   npm run dev

3. Open http://localhost:5173

How to build for production
---------------------------
1. From the repo root run:

   npm run build

2. The static files will be written to `dist/kitchen-ui`.

Docker integration
------------------
The `dockerfiles/node-manager/Dockerfile` has been updated to copy the `dist` folder
into `/app/ui/kitchen` if present. When running the container, the HTTP server will
serve static UI assets at the `/ui` path. Build the UI separately and include the
`dist/kitchen-ui` directory when building the Docker image (we do not attempt to
build the UI inside the Python image).

Notes and future work
---------------------
- Integration with backend APIs: the current UI uses mock data. We'll wire up
  real REST endpoints in a follow-up change.
- Component extraction: `CanvasGraph` is written to be configurable and exported
  later as a standalone package/component.
