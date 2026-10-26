// 帐号—年级管理(按年级排课的权限分离):只有管理员能看全帐号、改年级。
// 空年级 = 不受限;年级是全校统一的数字,不绑定学期。

import { apiGet, apiPut } from '@/api/client'

export interface UserGradeItem {
  id: number
  username: string
  display_name: string
  roles: string[]
  grades: number[]
}

export const listUsersWithGrades = (): Promise<UserGradeItem[]> =>
  apiGet('/users')

export const setUserGrades = (userId: number, grades: number[]): Promise<number[]> =>
  apiPut(`/users/${userId}/grade-scopes`, { grades })

export const myGradeScopes = (): Promise<number[] | null> =>
  apiGet('/users/me/grade-scopes')
