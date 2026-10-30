/** A row of buttons of which one is pressed, or none when `value` matches no option. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-3 gap-0.5 rounded-md bg-muted p-[3px]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className="rounded-[5px] px-1 py-1 text-[0.85rem] text-muted-foreground aria-pressed:bg-card aria-pressed:font-medium aria-pressed:text-foreground aria-pressed:shadow-sm"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
