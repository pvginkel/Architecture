import { createApp } from "./app.js";

const port = Number(process.env.PORT ?? 8080);

const app = createApp();

app.listen(port, () => {
  console.log(`architecture service listening on :${port}`);
});
