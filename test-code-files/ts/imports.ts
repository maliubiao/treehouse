// 各种import样式
import { foo } from 'module';
import * as bar from 'module2';
import baz, { qux } from 'module3';
import('dynamic-module').then(m => m.init());
const lazyImport = await import('lazy-module');
import type { SomeType } from 'types-module';
import { reallyLongNamedExport as shortName } from 'very-long-module-name';
import defaultExport, { namedExport } from 'mixed-export-module';
import { nested: { deepImport } } from 'nested-module';
import './side-effects-only';
import {
  multiLineImport1,
  multiLineImport2,
  multiLineImport3
} from 'multi-line-module';