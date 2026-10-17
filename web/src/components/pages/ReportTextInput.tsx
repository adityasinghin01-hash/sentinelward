import {useState} from 'react';

/** Keep the caret and the person's exact edits stable while displaying readable source text at rest. */
export function ReportTextInput({value, format = value => value, onChange, label, multiline = false, rows = 3, disabled, maxLength = 2000, placeholder}: {
  value: string; format?: (value: string) => string; onChange: (value: string) => void;
  label: string; multiline?: boolean; rows?: number; disabled?: boolean; maxLength?: number; placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [buffer, setBuffer] = useState('');
  const Input = multiline ? 'textarea' : 'input';
  return <Input aria-label={label} value={editing ? buffer : format(value)} disabled={disabled} maxLength={maxLength} placeholder={placeholder}
    {...(multiline ? {rows} : {})}
    onFocus={() => {setBuffer(format(value)); setEditing(true);}}
    onBlur={() => setEditing(false)}
    onChange={e => {setBuffer(e.target.value); onChange(e.target.value);}} />;
}
