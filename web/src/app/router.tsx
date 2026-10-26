import { createBrowserRouter } from "react-router";
import { NotFound, RouteError } from "../pages/NotFound";
import { AppShell } from "./AppShell";

// Pages load on first visit, so the landing page doesn't ship the dashboard's code.
// The landing page stands alone; every dashboard page shares the shell with its sidebar.
export const routes = [
  {
    path: "/",
    errorElement: <RouteError />,
    // Shown for the moment a page's code is still loading on first visit.
    hydrateFallbackElement: <p className="visually-hidden">Loading</p>,
    children: [
      {
        index: true,
        lazy: () => import("../pages/LandingPage").then((m) => ({ Component: m.LandingPage })),
      },
      {
        element: <AppShell />,
        children: [
          {
            path: "overview",
            lazy: () => import("../pages/FleetPage").then((m) => ({ Component: m.FleetPage })),
          },
          {
            path: "models/:modelId",
            lazy: () => import("../pages/ModelPage").then((m) => ({ Component: m.ModelPage })),
          },
          {
            path: "models/:modelId/inputs",
            lazy: () =>
              import("../pages/ModelInputsPage").then((m) => ({ Component: m.ModelInputsPage })),
          },
          {
            path: "incidents",
            lazy: () =>
              import("../pages/IncidentsPage").then((m) => ({ Component: m.IncidentsPage })),
          },
          {
            path: "incidents/:incidentId",
            lazy: () =>
              import("../pages/IncidentPage").then((m) => ({ Component: m.IncidentPage })),
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
