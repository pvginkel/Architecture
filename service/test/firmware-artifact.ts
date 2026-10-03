/** The ANS-184 case: a live firmware string YAML 1.2 reads as a float overflowing to Infinity. */
export function firmwareArtifact(): { text: string; line: number } {
  const device = (n: number, firmware: string) =>
    [
      `  - id: device:dev${n},77777777-7777-4777-8777-77777777777${n}`,
      `    label: Device ${n}`,
      `    summary: Test device ${n}.`,
      `    introduced: 2026-10-03`,
      `    lifecycle: active`,
      `    stats:`,
      `      firmware: ${firmware}`,
    ].join("\n");
  const text = [
    `schemaVersion: "0.1"`,
    `producer: example`,
    `devices:`,
    device(0, `"1.2.3"`),
    device(1, `abc123`),
    device(2, `"9e10234"`),
    device(3, `9e10234`),
    ``,
  ].join("\n");
  const line = text.split("\n").indexOf("      firmware: 9e10234") + 1;
  return { text, line };
}
