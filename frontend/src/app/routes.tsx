import { createBrowserRouter } from "react-router";
import Root from "./Root";
import AdminAccessPage from "./pages/AdminAccessPage";
import DeliveryV2Page from "./pages/DeliveryV2Page";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: DeliveryV2Page },
      { path: "delivery", Component: DeliveryV2Page },
      { path: "admin/access", Component: AdminAccessPage },
    ],
  },
]);
