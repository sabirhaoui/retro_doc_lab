// Synthetic example; no Angular build or execution is needed.
import { Component } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Component({ selector: 'example-item', template: '<button (click)="load()">Load</button>' })
export class ItemComponent {
  state = 'idle';
  constructor(private http: HttpClient) {}
  load() {
    this.state = 'loading';
    this.http.get('/api/items/42').subscribe({
      next: () => { this.state = 'loaded'; },
      error: () => { this.state = 'error'; }
    });
  }
}
