import {Toaster as SonnerToaster} from 'sonner';
import {useTheme} from '../lib/theme';

export {toast} from 'sonner';
export function Toaster(){const theme=useTheme();return <SonnerToaster theme={theme} position="bottom-right" visibleToasts={3} duration={5000} closeButton toastOptions={{className:'sw-toast'}}/>}
