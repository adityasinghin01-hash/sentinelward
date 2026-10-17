import {PageTitle, Empty} from '../components/ui';

// Temporary stand-in while the remaining screens are built; it never shows patient data.
export function PlaceholderPage({title}: {title: string}) {
  return (
    <div className="page">
      <PageTitle eyebrow="SentinelWard" title={title} description="This screen is being built." />
      <Empty title={`${title} is coming`} detail="The ward screen is live now; this screen follows next." />
    </div>
  );
}
