import { config } from '@vue/test-utils'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  value: ResizeObserverStub,
  configurable: true,
})

config.global.stubs = {
  RouterLink: { template: '<a><slot /></a>' },
  ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  ElIcon: { template: '<i><slot /></i>' },
  ElTable: { template: '<div><slot /></div>' },
  ElTableColumn: { template: '<div><slot :row="{}" /></div>' },
  ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<div><slot /></div>' },
  ElInput: { template: '<input />' },
  ElUpload: { template: '<div><slot /><slot name="tip" /></div>' },
  ElPagination: true,
}

config.global.mocks = {
  $router: { push: () => undefined },
}
