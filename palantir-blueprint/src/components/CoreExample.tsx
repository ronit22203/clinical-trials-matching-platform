import { useState } from "react";
import {
  Button,
  Card,
  Dialog,
  DialogBody,
  DialogFooter,
  Elevation,
  H4,
  H5,
  Tag,
  Intent,
  Callout,
  HTMLTable,
} from "@blueprintjs/core";

export default function CoreExample() {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", maxWidth: "900px" }}>
      {/* Buttons */}
      <Card elevation={Elevation.TWO}>
        <H4>Buttons</H4>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <Button text="Default" />
          <Button intent={Intent.PRIMARY} text="Primary" />
          <Button intent={Intent.SUCCESS} text="Success" icon="tick" />
          <Button intent={Intent.WARNING} text="Warning" icon="warning-sign" />
          <Button intent={Intent.DANGER} text="Danger" icon="trash" />
          <Button minimal text="Minimal" />
          <Button outlined intent={Intent.PRIMARY} text="Outlined" />
          <Button loading text="Loading" />
          <Button disabled text="Disabled" />
        </div>
      </Card>

      {/* Tags */}
      <Card elevation={Elevation.TWO}>
        <H4>Tags</H4>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <Tag>Default</Tag>
          <Tag intent={Intent.PRIMARY}>Primary</Tag>
          <Tag intent={Intent.SUCCESS}>Success</Tag>
          <Tag intent={Intent.WARNING}>Warning</Tag>
          <Tag intent={Intent.DANGER}>Danger</Tag>
          <Tag round>Rounded</Tag>
          <Tag icon="user">With Icon</Tag>
        </div>
      </Card>

      {/* Callouts */}
      <Card elevation={Elevation.TWO}>
        <H4>Callouts</H4>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <Callout title="Info" icon="info-sign">
            Blueprint provides accessible, battle-tested components for enterprise UIs.
          </Callout>
          <Callout intent={Intent.SUCCESS} title="Success" icon="tick-circle">
            Component installed and rendering correctly.
          </Callout>
          <Callout intent={Intent.WARNING} title="Warning" icon="warning-sign">
            Peer dependency mismatch detected — review before production.
          </Callout>
          <Callout intent={Intent.DANGER} title="Error" icon="error">
            Critical failure in downstream service.
          </Callout>
        </div>
      </Card>

      {/* Table */}
      <Card elevation={Elevation.TWO}>
        <H4>HTML Table</H4>
        <HTMLTable striped bordered interactive style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Service</th>
              <th>Status</th>
              <th>Latency</th>
              <th>Region</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Auth Gateway</td>
              <td><Tag intent={Intent.SUCCESS}>Healthy</Tag></td>
              <td>12ms</td>
              <td>us-east-1</td>
            </tr>
            <tr>
              <td>Data Pipeline</td>
              <td><Tag intent={Intent.WARNING}>Degraded</Tag></td>
              <td>340ms</td>
              <td>eu-west-2</td>
            </tr>
            <tr>
              <td>Inference Engine</td>
              <td><Tag intent={Intent.DANGER}>Down</Tag></td>
              <td>—</td>
              <td>ap-south-1</td>
            </tr>
          </tbody>
        </HTMLTable>
      </Card>

      {/* Dialog trigger */}
      <Card elevation={Elevation.TWO}>
        <H4>Dialog</H4>
        <Button intent={Intent.PRIMARY} icon="info-sign" text="Open Dialog" onClick={() => setDialogOpen(true)} />
        <Dialog
          isOpen={dialogOpen}
          onClose={() => setDialogOpen(false)}
          title="System Status"
          icon="info-sign"
        >
          <DialogBody>
            <H5>All systems operational</H5>
            <p>Blueprint Dialog renders in a portal, above all other content. Use it for confirmations, forms, and detail views.</p>
          </DialogBody>
          <DialogFooter
            actions={
              <>
                <Button text="Cancel" onClick={() => setDialogOpen(false)} />
                <Button intent={Intent.PRIMARY} text="Confirm" onClick={() => setDialogOpen(false)} />
              </>
            }
          />
        </Dialog>
      </Card>
    </div>
  );
}
