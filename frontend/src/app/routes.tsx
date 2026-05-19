import { createBrowserRouter } from "react-router";
import Root from "./Root";
import DeliveryV2Page from "./pages/DeliveryV2Page";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: DeliveryV2Page },
      { path: "delivery", Component: DeliveryV2Page },
    ],
  },
]);
