import type {ReactNode} from 'react';

export function PageHeader({title, description, children}: {title: string; description: string; children?: ReactNode}) {
  return <header className="page-heading pages-heading">
    <div><h1>{title}</h1><p>{description}</p></div>
    {children && <div className="heading-controls">{children}</div>}
  </header>;
}
